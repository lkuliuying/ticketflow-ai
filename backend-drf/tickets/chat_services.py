from functools import partial
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from identity.services import UserInfo
from tickets.cache import check_rate
from tickets.media import mark_media_permanent, resolve_owned_media
from tickets.models import Status, Ticket, TicketChatMessage, TicketChatReadState
from tickets.notify import broadcast_chat_event, notify_users
from tickets.policy import TicketAccess

MAX_CHAT_TEXT = 4000
MEDIA_PLACEHOLDER = {
    str(TicketChatMessage.Kind.IMAGE): "[图片]",
    str(TicketChatMessage.Kind.VIDEO): "[视频]",
}


def chat_state(ticket: Ticket, access: TicketAccess) -> dict[str, Any]:
    if ticket.status == Status.CLOSED:
        return {"can_send": False, "lock_reason": "CLOSED"}
    if ticket.status == Status.OPEN:
        return {"can_send": False, "lock_reason": "WAITING_ACCEPT"}
    if ticket.status == Status.REOPENED:
        return {"can_send": False, "lock_reason": "WAITING_RESUME"}
    if ticket.assignee_id is None:
        return {"can_send": False, "lock_reason": "UNASSIGNED"}
    if access.user_id != ticket.submitter_id and not access.can_handle(ticket):
        return {"can_send": False, "lock_reason": "READ_ONLY"}
    return {"can_send": True, "lock_reason": ""}


def serialize_chat_message(msg: TicketChatMessage, ticket_id: UUID) -> dict[str, Any]:
    file_url = None
    thumb_url = None
    if msg.kind in (TicketChatMessage.Kind.IMAGE, TicketChatMessage.Kind.VIDEO) and not msg.media_expired:
        if msg.attachment_id is not None:
            file_url = f"/api/tickets/{ticket_id}/chat/messages/{msg.pk}/file"
            if msg.kind == TicketChatMessage.Kind.IMAGE:
                thumb_url = f"{file_url}?size=thumb"
    return {
        "id": str(msg.pk),
        "ticket_id": str(ticket_id),
        "sender_id": msg.sender_id,
        "sender_name": msg.sender.username if msg.sender else "系统",
        "kind": msg.kind,
        "content": msg.content,
        "media_meta": msg.media_meta or {},
        "media_expired": msg.media_expired,
        "file_url": file_url,
        "thumb_url": thumb_url,
        "client_msg_id": msg.client_msg_id,
        "created_time": msg.created_time.isoformat(),
    }


def unread_counts(ticket_ids: list[UUID], user_id: int) -> dict[UUID, int]:
    if not ticket_ids:
        return {}
    last_read = Subquery(
        TicketChatReadState.objects.filter(ticket_id=OuterRef("ticket_id"), user_id=user_id).values("last_read_time")[
            :1
        ]
    )
    rows = (
        TicketChatMessage.objects.filter(ticket_id__in=ticket_ids)
        .exclude(sender_id=user_id)
        .annotate(last_read=last_read)
        .filter(Q(last_read__isnull=True) | Q(created_time__gt=OuterRef("last_read")) if False else Q())
    )
    # Use F expression cleanly against the annotated subquery.
    from django.db.models import F

    counts = (
        rows.filter(Q(last_read__isnull=True) | Q(created_time__gt=F("last_read")))
        .values("ticket_id")
        .annotate(total=Count("pk"))
        .values_list("ticket_id", "total")
    )
    return {tid: int(total) for tid, total in counts}


def list_chat_messages(
    ticket: Ticket,
    access: TicketAccess,
    *,
    limit: int = 50,
    before_id: UUID | None = None,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    queryset = ticket.chat_messages.select_related("sender")
    if before_id is not None:
        pivot = ticket.chat_messages.filter(pk=before_id).values("created_time", "pk").first()
        if pivot is not None:
            queryset = queryset.filter(
                Q(created_time__lt=pivot["created_time"]) | Q(created_time=pivot["created_time"], pk__lt=pivot["pk"])
            )
    if after_id is not None:
        pivot = ticket.chat_messages.filter(pk=after_id).values("created_time", "pk").first()
        if pivot is not None:
            queryset = queryset.filter(
                Q(created_time__gt=pivot["created_time"]) | Q(created_time=pivot["created_time"], pk__gt=pivot["pk"])
            )
            items = list(queryset.order_by("created_time", "id")[:limit])
            return {
                "results": [serialize_chat_message(row, ticket.pk) for row in items],
                "has_more": False,
                "chat_state": chat_state(ticket, access),
            }
    rows = list(queryset.order_by("-created_time", "-id")[: limit + 1])
    has_more = len(rows) > limit
    items = list(reversed(rows[:limit]))
    return {
        "results": [serialize_chat_message(row, ticket.pk) for row in items],
        "has_more": has_more,
        "chat_state": chat_state(ticket, access),
    }


@transaction.atomic
def send_chat_message(
    queryset: QuerySet[Ticket],
    ticket_id: UUID,
    user: UserInfo,
    access: TicketAccess,
    *,
    kind: str,
    content: str = "",
    file_pk: int | None = None,
    client_msg_id: str = "",
) -> tuple[TicketChatMessage, bool]:
    check_rate(user.pk, "chat", 120)
    visible_ids = queryset.order_by().values("pk")
    ticket = Ticket.objects.select_for_update().filter(pk=ticket_id, pk__in=visible_ids).first()
    if ticket is None:
        raise NotFound("工单不存在")
    state = chat_state(ticket, access)
    if not state["can_send"]:
        raise PermissionDenied("当前工单会话不可发送消息")
    cleaned_client_id = client_msg_id.strip()[:64]
    if cleaned_client_id:
        existing = (
            TicketChatMessage.objects.select_related("sender")
            .filter(ticket=ticket, sender=user, client_msg_id=cleaned_client_id)
            .first()
        )
        if existing is not None:
            return existing, False
    cleaned_content = content.strip()
    upload = None
    media_meta: dict[str, Any] = {}
    if kind == TicketChatMessage.Kind.TEXT:
        if not cleaned_content or len(cleaned_content) > MAX_CHAT_TEXT:
            raise ValidationError({"content": f"消息内容须在 1 至 {MAX_CHAT_TEXT} 字符之间"})
    elif kind in (TicketChatMessage.Kind.IMAGE, TicketChatMessage.Kind.VIDEO):
        if file_pk is None:
            raise ValidationError({"file_pk": "图片或视频消息必须提供附件标识"})
        upload = resolve_owned_media(user, file_pk, expected_kind=kind)
        mark_media_permanent([upload])
        media_meta = {
            "filename": upload.filename,
            "filesize": upload.filesize,
            "mime_type": upload.mime_type or "",
        }
        cleaned_content = cleaned_content[:MAX_CHAT_TEXT]
    else:
        raise ValidationError({"kind": "不支持的消息类型"})
    try:
        with transaction.atomic():
            msg = TicketChatMessage.objects.create(
                ticket=ticket,
                sender=user,
                kind=kind,
                content=cleaned_content,
                attachment=upload,
                media_meta=media_meta,
                client_msg_id=cleaned_client_id,
            )
    except IntegrityError:
        existing = TicketChatMessage.objects.select_related("sender").get(
            ticket=ticket, sender=user, client_msg_id=cleaned_client_id
        )
        return existing, False
    if access.can_handle(ticket) and user.pk != ticket.submitter_id and ticket.first_response_at is None:
        ticket.first_response_at = msg.created_time
        ticket.save(update_fields=["first_response_at", "updated_time"])
    TicketChatReadState.objects.update_or_create(
        ticket=ticket, user=user, defaults={"last_read_time": msg.created_time}
    )
    payload = serialize_chat_message(msg, ticket.pk)
    transaction.on_commit(partial(broadcast_chat_event, ticket.pk, "chat_message", payload), robust=True)
    preview_text = cleaned_content[:120] if cleaned_content else MEDIA_PLACEHOLDER.get(kind, "[媒体消息]")
    recipient_id = ticket.assignee_id if user.pk == ticket.submitter_id else ticket.submitter_id
    if recipient_id and recipient_id != user.pk:
        transaction.on_commit(
            partial(
                notify_users,
                [recipient_id],
                f"工单 {ticket.number} 收到新消息",
                f"{user.username}：{preview_text}",
            ),
            robust=True,
        )
    return msg, True


def mark_chat_read(ticket: Ticket, user: UserInfo) -> None:
    TicketChatReadState.objects.update_or_create(ticket=ticket, user=user, defaults={"last_read_time": timezone.now()})


def recent_chat_context(ticket: Ticket, *, limit: int = 12, max_chars: int = 4000) -> list[dict[str, str]]:
    """Return bounded text summary of recent chat messages for AI prompts."""
    rows = list(ticket.chat_messages.select_related("sender").order_by("-created_time", "-id")[:limit])
    turns: list[dict[str, str]] = []
    remaining = max_chars
    for row in rows:
        label = MEDIA_PLACEHOLDER.get(row.kind, "")
        filename = str((row.media_meta or {}).get("filename", "") or "")
        media_note = f"{label[:-1]}: {filename}]" if label and filename else label
        text = " ".join(part for part in (media_note, row.content) if part).strip()
        if not text:
            continue
        clipped = text[:remaining]
        remaining -= len(clipped)
        role = "submitter" if row.sender_id == ticket.submitter_id else "handler" if row.sender_id else "system"
        turns.append(
            {
                "role": role,
                "sender": row.sender.username if row.sender else "系统",
                "content": clipped,
                "created_time": row.created_time.isoformat(),
            }
        )
        if remaining <= 0:
            break
    turns.reverse()
    return turns
