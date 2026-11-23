from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from identity.models import UserInfo
from tests.integration.tickets.test_ticket_services import race_twice
from tickets.models import Status, Ticket, TicketAssignment, TicketComment, Visibility
from tickets.policy import TicketAccess
from tickets.services import create_ticket, transition


def technician(agent, username):
    user = UserInfo.objects.create_user(username=username, dept=agent.dept)
    user.roles.set(agent.roles.all())
    return user


@pytest.mark.django_db
def test_dispatch_uses_open_workload_then_oldest_assignment_then_username(users, make_ticket, details):
    agent = users["agent"]
    alpha = technician(agent, "alpha")
    beta = technician(agent, "beta")
    previous = make_ticket(status=Status.CLOSED, assignee=alpha)
    old = timezone.now() - timedelta(days=1)
    TicketAssignment.objects.create(ticket=previous, assignee=alpha, started_at=old, ended_at=old)
    make_ticket(assignee=agent)

    def submit():
        ticket, created = create_ticket(users["requester"], str(uuid4()), details)
        assert created
        assignment = ticket.assignments.get(ended_at__isnull=True)
        assert assignment.assigned_by_id is None
        assert ticket.logs.get(action="AUTO_ASSIGN").operator_id is None
        return ticket.assignee

    assert submit() == beta  # 未派单者排在已派过单的人之前。
    assert submit() == alpha  # 关闭的工单不计入工作量。
    assert submit() == agent  # 负载相同且从未被派单。
    assert submit() == beta  # 负载相同，最近一次派单最早。


@pytest.mark.django_db
def test_dispatch_breaks_exact_ties_by_username_and_excludes_submitter(users, details):
    agent = users["agent"]
    alpha = technician(agent, "alpha")
    technician(agent, "beta")
    ticket, _ = create_ticket(agent, str(uuid4()), details)
    assert ticket.assignee == alpha


@pytest.mark.django_db
def test_automatic_assignment_names_the_system_actor_in_both_timelines(users, client_for, details):
    ticket, _ = create_ticket(users["requester"], str(uuid4()), details)
    api = client_for(users["agent"])
    path = f"/api/tickets/{ticket.pk}"
    detail, timeline = api.get(path), api.get(f"{path}/timeline")
    assert detail.status_code == timeline.status_code == 200
    for result in (detail.json()["data"]["timeline"], timeline.json()["data"]):
        assigned = [item["actor"] for item in result["results"] if item["action"] == "AUTO_ASSIGN"]
        assert assigned == ["系统"]


@pytest.mark.django_db
def test_dispatch_leaves_ticket_pending_when_no_eligible_technician(users, details):
    agent = users["agent"]
    expired = technician(agent, "expired")
    expired.date_expired = timezone.now() - timedelta(seconds=1)
    expired.save(update_fields=["date_expired"])
    disabled = technician(agent, "disabled")
    disabled.is_active = False
    disabled.save(update_fields=["is_active"])

    ticket, _ = create_ticket(agent, str(uuid4()), details)
    assert ticket.assignee_id is None
    assert not ticket.assignments.exists()
    assert list(ticket.logs.values_list("action", flat=True)) == ["CREATE"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_create_balances_work_in_the_same_skill_group(support, requester, agent, details):
    other = technician(agent, "support-other")
    results = race_twice(lambda: create_ticket(requester, str(uuid4()), details))
    assert all(created for _, created in results)
    assert {ticket.assignee_id for ticket, _ in results} == {agent.pk, other.pk}
    assert TicketAssignment.objects.filter(ended_at__isnull=True).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("eligible_replacement", [False, True])
def test_reopen_dispatches_again_if_previous_handler_is_no_longer_eligible(users, make_ticket, eligible_replacement):
    agent = users["agent"]
    agent.is_active = False
    agent.save(update_fields=["is_active"])
    replacement = technician(agent, "replacement") if eligible_replacement else None
    ticket = make_ticket(status=Status.CLOSED, assignee=agent)
    now = timezone.now()
    previous = ticket.assignments.create(assignee=agent, started_at=now, ended_at=now, end_reason="CLOSED_OUT")

    owner = users["requester"]
    reopened = transition(Ticket.objects.all(), ticket.pk, owner, TicketAccess.for_user(owner), 1, Status.REOPENED)
    assert reopened.assignee == replacement
    assert reopened.status == Status.REOPENED
    previous.refresh_from_db()
    assert previous.ended_at == now
    assert reopened.assignments.filter(ended_at__isnull=True).count() == int(eligible_replacement)
    assert reopened.logs.filter(action="REOPEN_ASSIGN", operator=None).count() == int(eligible_replacement)


@pytest.mark.django_db
def test_return_preserves_status_and_makes_the_previous_technician_read_only(
    users, make_ticket, client_for, django_capture_on_commit_callbacks
):
    agent = users["agent"]
    admin = client_for(users["admin"])
    operator = client_for(agent)
    ticket = make_ticket(status=Status.IN_PROGRESS)
    path = f"/api/tickets/{ticket.pk}"
    assigned = admin.post(f"{path}/assign", {"assignee_id": agent.pk, "version": 1}, format="json")
    assert assigned.status_code == 200, assigned.data
    TicketComment.objects.create(ticket=ticket, author=agent, body="排查记录", visibility=Visibility.INTERNAL)
    assert operator.get(path).data["data"]["viewer"]["can_return"] is True
    assert operator.get(f"{path}/ai-context").status_code == 200
    assert admin.get("/api/tickets/dashboard").data["data"]["assignment"] == {"unassigned": 0}

    reason = "需要转给网络支持组"
    for invalid in ("", " " * 4, "长" * 501):
        response = operator.post(f"{path}/return", {"version": 2, "reason": invalid}, format="json")
        assert response.status_code == 400, response.data
    assert operator.post(f"{path}/return", {"version": 1, "reason": reason}, format="json").status_code == 409
    with django_capture_on_commit_callbacks(execute=True):
        returned = operator.post(f"{path}/return", {"version": 2, "reason": reason}, format="json")
    assert returned.status_code == 200, returned.data
    data = returned.data["data"]
    assert (data["assignee_id"], data["status"], data["version"]) == (None, Status.IN_PROGRESS, 3)
    history = ticket.assignments.get()
    assert history.ended_at is not None and history.end_reason == TicketAssignment.EndReason.RETURNED
    assert history.note == ticket.logs.get(action="RETURN").note == reason
    assert admin.get("/api/tickets/dashboard").data["data"]["assignment"] == {"unassigned": 1}
    viewed = operator.get(path).data["data"]
    assert viewed["viewer"]["read_only"] is True
    assert not any(value for key, value in viewed["viewer"].items() if key != "read_only")
    assert viewed["available_transitions"] == ()
    assert viewed["timeline"]["total"] == operator.get(f"{path}/timeline").data["data"]["total"] == 3
    assert client_for(users["requester"]).get(path).data["data"]["timeline"]["total"] == 0

    for action, payload in (
        ("transition", {"target_status": Status.PENDING_VERIFY, "version": 2}),
        ("comments", {"visibility": Visibility.PUBLIC, "body": "补充"}),
        ("ai-metadata", {"version": 2, "summary": "草稿", "tags": []}),
        ("return", {"version": 2, "reason": reason}),
    ):
        response = operator.post(f"{path}/{action}", payload, format="json")
        assert response.status_code == 403, response.data
    assert operator.get(f"{path}/ai-context").status_code == 403

    replace = technician(agent, "replacement")
    reassigned = admin.post(f"{path}/assign", {"assignee_id": replace.pk, "version": 3}, format="json")
    assert reassigned.status_code == 200, reassigned.data
    assert ticket.assignments.get(ended_at__isnull=True).assignee == replace
    changed = admin.post(f"{path}/assign", {"assignee_id": agent.pk, "version": 4}, format="json")
    assert changed.status_code == 200, changed.data
    assert ticket.assignments.get(assignee=replace).end_reason == TicketAssignment.EndReason.REASSIGNED
    assert operator.get(path).data["data"]["viewer"]["read_only"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "target", "available"),
    [
        (Status.PENDING_VERIFY, Status.CLOSED, (Status.CLOSED, Status.IN_PROGRESS)),
        (Status.PENDING_VERIFY, Status.IN_PROGRESS, (Status.CLOSED, Status.IN_PROGRESS)),
        (Status.CLOSED, Status.REOPENED, (Status.REOPENED,)),
    ],
)
def test_historical_technician_keeps_own_ticket_submitter_actions(
    users, make_ticket, client_for, status, target, available
):
    author = users["agent"]
    current = technician(author, "current-handler")
    ticket = make_ticket(author, status=status, assignee=current)
    now = timezone.now()
    ticket.assignments.create(assignee=author, started_at=now, ended_at=now, end_reason="REASSIGNED")
    api = client_for(author)
    path = f"/api/tickets/{ticket.pk}"

    detail = api.get(path)
    assert detail.status_code == 200, detail.data
    data = detail.data["data"]
    assert data["viewer"] == {
        "read_only": True,
        "can_handle": False,
        "can_assign": False,
        "can_return": False,
        "can_reply": True,
        "can_comment_internal": False,
        "can_archive": status == Status.CLOSED,
    }
    assert data["available_transitions"] == available
    assert api.get(f"{path}/ai-context").status_code == 403

    for visibility, expected in ((Visibility.PUBLIC, 201), (Visibility.INTERNAL, 403)):
        result = api.post(f"{path}/comments", {"body": "验收说明", "visibility": visibility}, format="json")
        assert result.status_code == expected, result.data
    result = api.post(f"{path}/transition", {"version": ticket.version, "target_status": target}, format="json")
    assert result.status_code == 200, result.data
    assert result.data["data"]["status"] == target


@pytest.mark.django_db
def test_assignment_filters_match_scoped_lists_and_dashboard_counts(users, make_ticket, client_for):
    agent = users["agent"]
    own = make_ticket(agent)
    current = make_ticket(assignee=agent)
    history = make_ticket()
    hidden = make_ticket()
    closed_unassigned = make_ticket(status=Status.CLOSED)
    now = timezone.now()
    for ticket in (history, current):
        ticket.assignments.create(assignee=agent, started_at=now, ended_at=now, end_reason="REASSIGNED")

    def ticket_ids(api, **params):
        response = api.get("/api/tickets", params)
        assert response.status_code == 200, response.data
        return {row["pk"] for row in response.data["data"]["results"]}

    technician_api = client_for(agent)
    employee = client_for(users["requester"])
    admin = client_for(users["admin"])
    assert ticket_ids(technician_api) == {str(ticket.pk) for ticket in (own, current, history)}
    assert ticket_ids(employee) == {str(ticket.pk) for ticket in (current, history, hidden, closed_unassigned)}
    assert len(ticket_ids(admin)) == 5
    assert ticket_ids(technician_api, assignment="current") == {str(current.pk)}
    assert ticket_ids(technician_api, assignment="history") == {str(history.pk)}
    assert not ticket_ids(technician_api, assignment="unassigned")
    assert ticket_ids(admin, assignment="unassigned") == {str(ticket.pk) for ticket in (own, history, hidden)}

    url = "/api/tickets/dashboard"
    assert technician_api.get(url).data["data"]["assignment"] == {"current": 1, "history": 1}
    assert technician_api.get(url, {"assignment": "history"}).data["data"]["assignment"] == {"current": 0, "history": 1}
    assert technician_api.get(url, {"assignment": "unassigned"}).data["data"]["assignment"] == {
        "current": 0,
        "history": 0,
    }
    assert employee.get(url).data["data"]["assignment"] == {}
    assert admin.get(url).data["data"]["assignment"] == {"unassigned": 3}
