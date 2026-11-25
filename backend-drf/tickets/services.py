import json
import secrets
from datetime import timedelta
from functools import partial
from hashlib import sha256
from typing import NotRequired, TypedDict, Unpack
from uuid import UUID, uuid4

from django.core.cache import cache
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from identity.models import DeptInfo, UserInfo
from tickets.assignment import dispatch, end_assignment, set_assignee
from tickets.assistant_services import owned_session, require_employee
from tickets.cache import IDEMPOTENCY_TTL, invalidate_dashboard, request_key, reserve_create
from tickets.media import mark_media_permanent, resolve_owned_media
from tickets.models import (
    Priority,
    Status,
    Ticket,
    TicketAssignment,
    TicketAttachment,
    TicketComment,
    TicketCreateRequest,
    TicketLog,
    TicketRating,
    Visibility,
)
from tickets.notify import broadcast_chat_event, notify_users
from tickets.policy import ADMIN_ROLE, TRANSITIONS, TicketAccess, assignment_candidates
from tickets.skill_groups import destination

SLA_HOURS = {str(Priority.P0): 2, str(Priority.P1): 8, str(Priority.P2): 24, str(Priority.P3): 72}
SLA_WARNING = timedelta(minutes=30)
NUMBER_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_ticket_number() -> str:
    day = timezone.localdate().strftime("%Y%m%d")
    suffix = "".join(secrets.choice(NUMBER_ALPHABET) for _ in range(6))
    return f"TF-{day}-{suffix}"


def _affected_users(ticket: Ticket, *extra_ids: int | None) -> tuple[int | None, ...]:
    past_ids = ticket.assignments.order_by().values_list("assignee_id", flat=True).distinct()
    return (ticket.submitter_id, ticket.assignee_id, *extra_ids, *past_ids)


class TicketConflict(APIException):
    status_code = 409
    default_detail = "工单已变更，请刷新后重试"


class NewTicket(TypedDict):
    title: str
    description: str
    category: str
    priority: str


class RatingInput(TypedDict):
    resolved: bool
    satisfaction: int
    handler_score: int
    tags: NotRequired[list[str]]
    comment: NotRequired[str | None]


def _admin_user_ids() -> list[int]:
    return list(
        UserInfo.objects.filter(
            is_active=True,
            roles__code=ADMIN_ROLE,
            roles__is_active=True,
            roles__deleted_at__isnull=True,
        )
        .values_list("pk", flat=True)
        .distinct()
    )


def _make_ticket(user: UserInfo, values: NewTicket) -> Ticket:
    ticket_id = uuid4()
    department = destination(values["category"])
    ticket = Ticket.objects.create(
        id=ticket_id,
        number=generate_ticket_number(),
        submitter=user,
        creator=user,
        modifier=user,
        department=department,
        dept_belong=department,
        sla_due_at=timezone.now() + timedelta(hours=SLA_HOURS[values["priority"]]),
        **values,
    )
    TicketLog.objects.create(ticket=ticket, action="CREATE", to_status=ticket.status, operator=user)
    dispatch(ticket)
    if ticket.assignee_id is not None:
        ticket.save(update_fields=["assignee"])
        transaction.on_commit(
            partial(
                notify_users,
                [ticket.assignee_id],
                f"新工单 {ticket.number} 已自动指派给您",
                f"标题：{ticket.title}",
            ),
            robust=True,
        )
    transaction.on_commit(partial(invalidate_dashboard, (ticket.submitter_id, ticket.assignee_id)), robust=True)
    return ticket


def _cached_ticket(user: UserInfo, redis_key: str, digest: str) -> Ticket | None:
    cached = cache.get(redis_key)
    if not cached:
        return None
    if digest != cached["hash"]:
        raise TicketConflict("相同幂等键已用于其他请求")
    return Ticket.objects.filter(pk=cached["ticket"], submitter=user).first()


def create_ticket(
    user: UserInfo,
    key: str,
    values: NewTicket,
    *,
    assistant_session_id: UUID | None = None,
    attachment_ids: list[int] | None = None,
) -> tuple[Ticket, bool]:
    key_hash = sha256(key.encode()).hexdigest()
    request_values: dict[str, object] = dict(values)
    if assistant_session_id is not None:
        require_employee(TicketAccess.for_user(user))
        request_values["assistant_session_id"] = str(assistant_session_id)
    cleaned_attachments = list(dict.fromkeys(attachment_ids or []))
    if cleaned_attachments:
        request_values["attachment_ids"] = [str(item) for item in cleaned_attachments]
    digest = sha256(json.dumps(request_values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    redis_key = request_key(user.pk, key_hash)
    existing = _cached_ticket(user, redis_key, digest)
    if existing is not None:
        return existing, False
    with reserve_create(redis_key):
        existing = _cached_ticket(user, redis_key, digest)
        if existing is not None:
            return existing, False
        return _persist_ticket(user, key_hash, digest, redis_key, values, assistant_session_id, cleaned_attachments)


@transaction.atomic
def _persist_ticket(
    user: UserInfo,
    key_hash: str,
    digest: str,
    redis_key: str,
    values: NewTicket,
    assistant_session_id: UUID | None = None,
    attachment_ids: list[int] | None = None,
) -> tuple[Ticket, bool]:
    now = timezone.now()
    record, inserted = TicketCreateRequest.objects.select_for_update().get_or_create(
        submitter=user,
        key_hash=key_hash,
        defaults={"request_hash": digest, "expires_at": now + timedelta(seconds=IDEMPOTENCY_TTL)},
    )
    if not inserted and record.expires_at > now:
        if record.request_hash != digest:
            raise TicketConflict("相同幂等键已用于其他请求")
        if record.ticket_id is not None:
            return record.ticket, False
    session = None
    if assistant_session_id is not None:
        session = owned_session(user.pk, assistant_session_id, lock=True)
        if session.ticket_id is not None:
            raise TicketConflict("此会话已关联工单")
    uploads = [resolve_owned_media(user, file_pk, expected_kind="IMAGE") for file_pk in (attachment_ids or [])]
    ticket = _make_ticket(user, values)
    if uploads:
        mark_media_permanent(uploads)
        TicketAttachment.objects.bulk_create(
            [
                TicketAttachment(ticket=ticket, file=upload, uploader=user, sort_order=idx)
                for idx, upload in enumerate(uploads)
            ]
        )
    if session is not None:
        session.ticket = ticket
        session.save(update_fields=["ticket", "updated_time"])
    record.ticket = ticket
    record.request_hash = digest
    record.expires_at = now + timedelta(seconds=IDEMPOTENCY_TTL)
    record.save(update_fields=["ticket", "request_hash", "expires_at"])
    transaction.on_commit(
        lambda: cache.set(redis_key, {"hash": digest, "ticket": str(ticket.pk)}, IDEMPOTENCY_TTL),
        robust=True,
    )
    return ticket, True


def _locked(queryset: QuerySet[Ticket], ticket_id: UUID) -> Ticket:
    try:
        visible_ids = queryset.order_by().values("pk")
        return Ticket.objects.select_for_update().get(pk=ticket_id, pk__in=visible_ids)
    except Ticket.DoesNotExist as exc:
        raise NotFound("工单不存在") from exc


def _check_version(ticket: Ticket, version: int) -> None:
    if ticket.version != version:
        raise TicketConflict()


@transaction.atomic
def create_rating(
    queryset: QuerySet[Ticket], ticket_id: UUID, user: UserInfo, **values: Unpack[RatingInput]
) -> TicketRating:
    ticket = _locked(queryset, ticket_id)
    if ticket.submitter_id != user.pk:
        raise PermissionDenied("仅工单提交人可评价")
    if ticket.status != Status.CLOSED:
        raise TicketConflict("仅已关闭的工单可评价")
    if TicketRating.objects.filter(ticket=ticket).exists():
        raise TicketConflict("工单已评价")
    return TicketRating.objects.create(ticket=ticket, rater=user, handler_id=ticket.assignee_id, **values)


def _record_change(
    ticket: Ticket,
    user: UserInfo,
    action: str,
    previous: str,
    fields: list[str],
    note: str = "",
    *,
    extra_users: tuple[int | None, ...] = (),
) -> Ticket:
    ticket.version += 1
    ticket.modifier = user
    ticket.save(update_fields=[*fields, "version", "modifier", "updated_time"])
    TicketLog.objects.create(
        ticket=ticket,
        action=action,
        from_status=previous,
        to_status=ticket.status,
        operator=user,
        note=note,
        internal=action in ("ASSIGN", "RETURN", "AI_METADATA", "DEACTIVATED"),
    )
    transaction.on_commit(partial(invalidate_dashboard, _affected_users(ticket, *extra_users)), robust=True)
    if action in ("TRANSITION", "ASSIGN", "RETURN", "DEACTIVATED"):
        transaction.on_commit(partial(broadcast_chat_event, ticket.pk, "chat_state", {}), robust=True)
    return ticket


@transaction.atomic
def transition(
    queryset: QuerySet[Ticket],
    ticket_id: UUID,
    user: UserInfo,
    access: TicketAccess,
    version: int,
    target_status: str,
    note: str = "",
) -> Ticket:
    if target_status == Status.REOPENED:
        group_ids = queryset.filter(pk=ticket_id).order_by().values("department_id")
        list(DeptInfo.objects.select_for_update(no_key=True).filter(pk__in=group_ids))
    ticket = _locked(queryset, ticket_id)
    allowed_targets = access.targets(ticket)
    if target_status not in allowed_targets and access.read_only(ticket):
        raise PermissionDenied("无权执行此流转")
    _check_version(ticket, version)
    previous = ticket.status
    if target_status not in TRANSITIONS.get(previous, ()):
        raise TicketConflict("当前状态不支持该流转")
    if target_status not in allowed_targets:
        raise PermissionDenied("无权执行此流转")
    ticket.status = target_status
    fields = ["status"]
    if target_status == Status.PENDING_VERIFY:
        ticket.resolved_at = timezone.now()
        fields.append("resolved_at")
    if previous == Status.PENDING_VERIFY and target_status == Status.IN_PROGRESS:
        ticket.resolved_at = None
        fields.append("resolved_at")
    if target_status == Status.CLOSED:
        end_assignment(ticket, str(TicketAssignment.EndReason.CLOSED_OUT))
    if target_status == Status.REOPENED:
        ticket.resolved_at = None
        ticket.sla_cycle += 1
        ticket.sla_due_at = timezone.now() + timedelta(hours=SLA_HOURS[ticket.priority])
        fields.extend(("resolved_at", "sla_cycle", "sla_due_at"))
        _record_change(ticket, user, "TRANSITION", previous, fields, note)
        dispatch(ticket, reopening=True)
        ticket.save(update_fields=["assignee"])
        return ticket
    return _record_change(ticket, user, "TRANSITION", previous, fields, note)


@transaction.atomic
def assign(
    queryset: QuerySet[Ticket],
    ticket_id: UUID,
    user: UserInfo,
    access: TicketAccess,
    version: int,
    assignee_id: int | None,
) -> Ticket:
    group_id = None
    if access.admin and assignee_id is not None:
        groups = UserInfo.objects.filter(pk=assignee_id).order_by().values("dept_id")
        group = DeptInfo.objects.select_for_update(no_key=True).filter(pk__in=groups).first()
        group_id = group.pk if group is not None else None
    ticket = _locked(queryset, ticket_id)
    if not access.admin:
        raise PermissionDenied("无权指派此工单")
    _check_version(ticket, version)
    if ticket.status == Status.CLOSED:
        raise TicketConflict("已关闭的工单不能指派")
    note = "取消指派"
    if assignee_id is not None:
        assignee = assignment_candidates().filter(pk=assignee_id, dept_id=group_id).first()
        if assignee is None:
            raise ValidationError({"assignee_id": "处理人不在可指派范围内"})
        note = f"处理人：{assignee.username}"
    previous_assignee = ticket.assignee_id
    set_assignee(ticket, assignee_id, user)
    if assignee_id is not None and assignee_id != user.pk:
        transaction.on_commit(
            partial(
                notify_users,
                [assignee_id],
                f"工单 {ticket.number} 已指派给您",
                f"标题：{ticket.title}",
            ),
            robust=True,
        )
    return _record_change(ticket, user, "ASSIGN", ticket.status, ["assignee"], note, extra_users=(previous_assignee,))


def release_assigned_tickets(assignee: UserInfo, actor: UserInfo, note: str) -> None:
    tickets = Ticket.objects.select_for_update().filter(assignee=assignee).exclude(status=Status.CLOSED).order_by("pk")
    for ticket in tickets:
        end_assignment(ticket, str(TicketAssignment.EndReason.DEACTIVATED), note)
        ticket.assignee_id = None
        _record_change(ticket, actor, "DEACTIVATED", ticket.status, ["assignee"], note, extra_users=(assignee.pk,))


@transaction.atomic
def return_ticket(
    queryset: QuerySet[Ticket], ticket_id: UUID, user: UserInfo, access: TicketAccess, version: int, reason: str
) -> Ticket:
    ticket = _locked(queryset, ticket_id)
    if access.admin or not access.can_handle(ticket):
        raise PermissionDenied("无权退回此工单")
    _check_version(ticket, version)
    if ticket.status == Status.CLOSED:
        raise TicketConflict("已关闭的工单不能退回")
    previous_status = ticket.status
    previous_assignee = ticket.assignee_id
    end_assignment(ticket, str(TicketAssignment.EndReason.RETURNED), reason)
    ticket.assignee_id = None
    fields = ["assignee"]
    if ticket.status == Status.IN_PROGRESS:
        ticket.status = Status.OPEN
        fields.append("status")
    transaction.on_commit(
        partial(
            notify_users,
            _admin_user_ids(),
            f"工单 {ticket.number} 已被退回待分配",
            f"退回人：{user.username}；原因：{reason}",
        ),
        robust=True,
    )
    return _record_change(ticket, user, "RETURN", previous_status, fields, reason, extra_users=(previous_assignee,))


@transaction.atomic
def add_comment(
    queryset: QuerySet[Ticket], ticket_id: UUID, user: UserInfo, access: TicketAccess, body: str, visibility: str
) -> TicketComment:
    ticket = _locked(queryset, ticket_id)
    handler = access.can_handle(ticket)
    allowed = handler if visibility == Visibility.INTERNAL else access.can_reply(ticket)
    if not allowed:
        raise PermissionDenied("无权写入此评论")
    comment = TicketComment.objects.create(ticket=ticket, author=user, body=body, visibility=visibility)
    if (
        handler
        and user.pk != ticket.submitter_id
        and visibility == Visibility.PUBLIC
        and ticket.first_response_at is None
    ):
        ticket.first_response_at = comment.created_time
        ticket.save(update_fields=["first_response_at", "updated_time"])
    return comment


@transaction.atomic
def save_ai_metadata(
    queryset: QuerySet[Ticket],
    ticket_id: UUID,
    user: UserInfo,
    access: TicketAccess,
    version: int,
    summary: str,
    tags: list[str],
    category: str | None = None,
    priority: str | None = None,
) -> Ticket:
    ticket = _locked(queryset, ticket_id)
    if not access.can_handle(ticket):
        raise PermissionDenied("无权更新此工单的 AI 建议")
    _check_version(ticket, version)
    if ticket.status == Status.CLOSED:
        raise TicketConflict("已关闭的工单不能修改 AI 建议")
    ticket.ai_summary = summary
    ticket.ai_tags = tags
    fields = ["ai_summary", "ai_tags"]
    note = ""
    if category is not None:
        ticket.category = category
        fields.append("category")
    if priority is not None and priority != ticket.priority:
        old_priority = ticket.priority
        ticket.priority = priority
        fields.append("priority")
        if ticket.resolved_at is None:
            cycle_start = ticket.sla_due_at - timedelta(hours=SLA_HOURS[old_priority])
            ticket.sla_due_at = cycle_start + timedelta(hours=SLA_HOURS[priority])
            fields.append("sla_due_at")
            note = f"优先级调整为 {priority}，已同步更新本轮 SLA"
    elif priority is not None:
        ticket.priority = priority
        fields.append("priority")
    return _record_change(ticket, user, "AI_METADATA", ticket.status, fields, note)
