from datetime import timedelta
from functools import partial

from celery import shared_task
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from common.core.modules import is_module_enabled
from tickets.models import Status, Ticket, TicketChatMessage, TicketCreateRequest, TicketSlaAlert
from tickets.notify import notify_users
from tickets.services import SLA_WARNING, _admin_user_ids


@shared_task
def scan_ticket_sla() -> int:
    """为即将到期和超时工单写入去重后的告警记录并发送站内提醒。"""
    if not is_module_enabled("ticketflow_tickets"):
        return 0
    now = timezone.now()
    active = Ticket.objects.filter(
        status__in=(Status.OPEN, Status.IN_PROGRESS, Status.REOPENED),
        resolved_at__isnull=True,
        sla_due_at__lte=now + SLA_WARNING,
    )
    has_overdue = Exists(
        TicketSlaAlert.objects.filter(
            ticket_id=OuterRef("pk"),
            sla_cycle=OuterRef("sla_cycle"),
            kind=TicketSlaAlert.Kind.OVERDUE,
        )
    )
    has_due_soon = Exists(
        TicketSlaAlert.objects.filter(
            ticket_id=OuterRef("pk"),
            sla_cycle=OuterRef("sla_cycle"),
            kind=TicketSlaAlert.Kind.DUE_SOON,
        )
    )
    pending = active.filter(
        (Q(sla_due_at__lte=now) & ~has_overdue)
        | (Q(sla_due_at__gt=now, sla_due_at__lte=now + SLA_WARNING) & ~has_due_soon)
    )
    count = 0
    for ticket_id in pending.order_by("pk").values_list("id", flat=True).iterator(chunk_size=256):
        with transaction.atomic():
            ticket = active.select_for_update(skip_locked=True).filter(pk=ticket_id).first()
            if ticket is not None:
                kind = TicketSlaAlert.Kind.OVERDUE if ticket.sla_due_at <= now else TicketSlaAlert.Kind.DUE_SOON
                _, created = TicketSlaAlert.objects.get_or_create(
                    ticket=ticket,
                    sla_cycle=ticket.sla_cycle,
                    kind=kind,
                    defaults={"sla_due_at": ticket.sla_due_at},
                )
                if created:
                    count += 1
                    label = "已超时" if kind == TicketSlaAlert.Kind.OVERDUE else "即将超时"
                    recipients = [ticket.assignee_id] if ticket.assignee_id is not None else _admin_user_ids()
                    transaction.on_commit(
                        partial(
                            notify_users,
                            recipients,
                            f"工单 {ticket.number} SLA {label}",
                            f"标题：{ticket.title}，截止时间：{ticket.sla_due_at.isoformat()}",
                        ),
                        robust=True,
                    )
    TicketCreateRequest.objects.filter(expires_at__lte=now).delete()
    return count


@shared_task
def cleanup_expired_ticket_videos(days: int = 90) -> int:
    """清理已关闭超过保留期的工单会话视频引用，保留文字记录与过期占位。"""
    if not is_module_enabled("ticketflow_tickets"):
        return 0
    cutoff = timezone.now() - timedelta(days=days)
    expired = TicketChatMessage.objects.filter(
        kind=TicketChatMessage.Kind.VIDEO,
        media_expired=False,
        ticket__status=Status.CLOSED,
        ticket__updated_time__lte=cutoff,
    )
    return int(expired.update(media_expired=True, attachment=None))
