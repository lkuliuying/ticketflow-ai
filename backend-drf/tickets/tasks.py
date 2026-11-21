from celery import shared_task
from django.db import transaction
from django.utils import timezone

from common.core.modules import is_module_enabled
from tickets.models import Status, Ticket, TicketCreateRequest, TicketSlaAlert
from tickets.services import SLA_WARNING


@shared_task
def scan_ticket_sla() -> int:
    """为即将到期和超时工单写入去重后的告警记录。"""
    if not is_module_enabled("ticketflow_tickets"):
        return 0
    now = timezone.now()
    active = Ticket.objects.filter(
        status__in=(Status.OPEN, Status.IN_PROGRESS, Status.REOPENED),
        resolved_at__isnull=True,
        sla_due_at__lte=now + SLA_WARNING,
    )
    count = 0
    for ticket_id in active.order_by("pk").values_list("id", flat=True).iterator(chunk_size=256):
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
                count += int(created)
    TicketCreateRequest.objects.filter(expires_at__lte=now).delete()
    return count
