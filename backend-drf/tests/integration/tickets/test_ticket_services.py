from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connections
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, Throttled

from identity.models import DeptInfo, UserInfo
from tickets.cache import check_rate
from tickets.models import Status, Ticket, TicketCreateRequest, TicketLog, TicketSlaAlert, Visibility
from tickets.policy import TicketAccess
from tickets.services import NewTicket, TicketConflict, add_comment, create_ticket, transition
from tickets.tasks import scan_ticket_sla


def race_twice[T](operation: Callable[[], T]) -> list[T]:
    start = Barrier(2, timeout=10)

    def execute() -> T:
        close_old_connections()
        try:
            start.wait()
            return operation()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute) for _ in range(2)]
        return [future.result(timeout=20) for future in futures]


@pytest.mark.django_db
def test_transitions_audit_and_reopen(
    support: DeptInfo, requester: UserInfo, agent: UserInfo, details: NewTicket
) -> None:
    ticket, _ = create_ticket(requester, str(uuid4()), details)
    staff = TicketAccess.for_user(agent)
    owner = TicketAccess.for_user(requester)
    tickets = Ticket.objects.all()
    with pytest.raises(TicketConflict):
        transition(tickets, ticket.pk, agent, staff, 1, Status.CLOSED)
    with pytest.raises(PermissionDenied):
        transition(tickets, ticket.pk, requester, owner, 1, Status.IN_PROGRESS)

    ticket = transition(tickets, ticket.pk, agent, staff, 1, Status.IN_PROGRESS)
    with pytest.raises(TicketConflict):
        transition(tickets, ticket.pk, agent, staff, 1, Status.PENDING_VERIFY)

    add_comment(tickets, ticket.pk, agent, staff, "内部排查", Visibility.INTERNAL)
    ticket.refresh_from_db()
    assert ticket.first_response_at is None
    public = add_comment(tickets, ticket.pk, agent, staff, "正在处理", Visibility.PUBLIC)
    ticket = transition(tickets, ticket.pk, agent, staff, 2, Status.PENDING_VERIFY)
    assert ticket.first_response_at == public.created_time
    assert ticket.resolved_at is not None
    ticket = transition(tickets, ticket.pk, requester, owner, 3, Status.CLOSED)
    ticket = transition(tickets, ticket.pk, requester, owner, 4, Status.REOPENED)
    assert (ticket.sla_cycle, ticket.version, ticket.resolved_at) == (2, 5, None)
    assert list(ticket.logs.order_by("created_time").values_list("to_status", flat=True)) == [
        Status.OPEN,
        Status.IN_PROGRESS,
        Status.PENDING_VERIFY,
        Status.CLOSED,
        Status.REOPENED,
    ]


@pytest.mark.django_db(transaction=True)
def test_concurrent_create_uses_one_database_record(support: DeptInfo, requester: UserInfo, details: NewTicket) -> None:
    key = str(uuid4())
    results = race_twice(lambda: create_ticket(requester, key, details))
    first, second = results
    assert first[0].pk == second[0].pk
    assert sorted([first[1], second[1]]) == [False, True]
    assert Ticket.objects.count() == TicketLog.objects.count() == TicketCreateRequest.objects.count() == 1
    with pytest.raises(TicketConflict):
        create_ticket(requester, key, {**details, "title": "不同标题"})


@pytest.mark.django_db(transaction=True)
def test_concurrent_update_rejects_stale_version(
    support: DeptInfo, requester: UserInfo, agent: UserInfo, details: NewTicket
) -> None:
    ticket, _ = create_ticket(requester, str(uuid4()), details)
    access = TicketAccess.for_user(agent)

    def start() -> bool:
        try:
            transition(Ticket.objects.all(), ticket.pk, agent, access, 1, Status.IN_PROGRESS)
        except TicketConflict:
            return False
        return True

    assert sorted(race_twice(start)) == [False, True]
    ticket.refresh_from_db()
    assert ticket.version == 2
    assert ticket.logs.filter(action="TRANSITION").count() == 1


@pytest.mark.django_db
def test_sla_alert_unique_per_kind_and_cycle(support: DeptInfo, requester: UserInfo, details: NewTicket) -> None:
    ticket, _ = create_ticket(requester, str(uuid4()), details)
    Ticket.objects.filter(pk=ticket.pk).update(sla_due_at=timezone.now() + timedelta(minutes=5))
    assert scan_ticket_sla.run() == 1
    assert scan_ticket_sla.run() == 0
    Ticket.objects.filter(pk=ticket.pk).update(sla_due_at=timezone.now() - timedelta(minutes=1))
    assert scan_ticket_sla.run() == 1
    assert scan_ticket_sla.run() == 0
    assert set(ticket.sla_alerts.values_list("kind", flat=True)) == {
        TicketSlaAlert.Kind.DUE_SOON,
        TicketSlaAlert.Kind.OVERDUE,
    }


def test_redis_sliding_rate_limit() -> None:
    action = f"test-{uuid4()}"
    check_rate(123, action, 2)
    check_rate(123, action, 2)
    with pytest.raises(Throttled) as error:
        check_rate(123, action, 2)
    assert error.value.wait is not None
    assert 0 < error.value.wait <= 60
    check_rate(124, action, 2)
