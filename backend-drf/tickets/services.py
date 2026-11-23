import json
from datetime import timedelta
from hashlib import sha256
from typing import TypedDict
from uuid import UUID, uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from identity.models import DeptInfo, UserInfo
from tickets.assignment import dispatch, end_assignment, set_assignee
from tickets.cache import IDEMPOTENCY_TTL, invalidate_dashboard, request_key, reserve_create
from tickets.models import (
    Priority,
    Status,
    Ticket,
    TicketAssignment,
    TicketComment,
    TicketCreateRequest,
    TicketLog,
    Visibility,
)
from tickets.policy import TRANSITIONS, TicketAccess, assignment_candidates

SLA_HOURS = {str(Priority.P0): 2, str(Priority.P1): 8, str(Priority.P2): 24, str(Priority.P3): 72}
SLA_WARNING = timedelta(minutes=30)


class TicketConflict(APIException):
    status_code = 409
    default_detail = "工单已变更，请刷新后重试"


class NewTicket(TypedDict):
    title: str
    description: str
    category: str
    priority: str


def _destination(category: str) -> DeptInfo:
    routing = getattr(settings, "TICKETFLOW_CATEGORY_DEPARTMENTS", {})
    dept_id = routing.get(category) or getattr(settings, "TICKETFLOW_DEFAULT_DEPARTMENT", None)
    departments = DeptInfo.objects.filter(is_active=True)
    dept = departments.filter(pk=dept_id).first() if dept_id else departments.filter(code="ticketflow_support").first()
    if dept is None:
        raise ValidationError({"department": "请配置可用的工单支持技能组"})
    return dept


def _make_ticket(user: UserInfo, values: NewTicket) -> Ticket:
    ticket_id = uuid4()
    department = _destination(values["category"])
    ticket = Ticket.objects.create(
        id=ticket_id,
        number=f"TF-{ticket_id.hex.upper()}",
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
    transaction.on_commit(invalidate_dashboard, robust=True)
    return ticket


def create_ticket(user: UserInfo, key: str, values: NewTicket) -> tuple[Ticket, bool]:
    key_hash = sha256(key.encode()).hexdigest()
    digest = sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    redis_key = request_key(user.pk, key_hash)
    cached = cache.get(redis_key)
    if cached:
        if digest != cached["hash"]:
            raise TicketConflict("相同幂等键已用于其他请求")
        ticket = Ticket.objects.filter(pk=cached["ticket"], submitter=user).first()
        if ticket is not None:
            return ticket, False
    with reserve_create(redis_key):
        return _persist_ticket(user, key_hash, digest, redis_key, values)


@transaction.atomic
def _persist_ticket(
    user: UserInfo, key_hash: str, digest: str, redis_key: str, values: NewTicket
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
    ticket = _make_ticket(user, values)
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


def _record_change(
    ticket: Ticket, user: UserInfo, action: str, previous: str, fields: list[str], note: str = ""
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
        internal=action in ("ASSIGN", "RETURN", "AI_METADATA"),
    )
    transaction.on_commit(invalidate_dashboard, robust=True)
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
    ticket = _locked(queryset, ticket_id)
    if not access.admin:
        raise PermissionDenied("无权指派此工单")
    _check_version(ticket, version)
    if ticket.status == Status.CLOSED:
        raise TicketConflict("已关闭的工单不能指派")
    note = "取消指派"
    if assignee_id is not None:
        assignee = assignment_candidates().filter(pk=assignee_id).first()
        if assignee is None:
            raise ValidationError({"assignee_id": "处理人不在可指派范围内"})
        note = f"处理人：{assignee.username}"
    set_assignee(ticket, assignee_id, user)
    return _record_change(ticket, user, "ASSIGN", ticket.status, ["assignee"], note)


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
    end_assignment(ticket, str(TicketAssignment.EndReason.RETURNED), reason)
    ticket.assignee_id = None
    return _record_change(ticket, user, "RETURN", ticket.status, ["assignee"], reason)


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
    ticket.ai_summary = summary
    ticket.ai_tags = tags
    fields = ["ai_summary", "ai_tags"]
    if category is not None:
        ticket.category = category
        fields.append("category")
    if priority is not None:
        ticket.priority = priority
        fields.append("priority")
    return _record_change(ticket, user, "AI_METADATA", ticket.status, fields)
