import secrets

import pytest
from django.core.management.base import CommandError

from identity.models import UserInfo
from knowledge.models import ArticleStatus, KnowledgeArticle
from ops.seed_ticketflow_demo import ADMIN, AGENT, NETWORK_AGENT, REQUESTER, USERNAMES, main, seed
from tickets.models import Priority, Status, Ticket, Visibility
from tickets.policy import ADMIN_ROLE, AGENT_ROLE, REQUESTER_ROLE, TicketAccess, has_permission


@pytest.mark.django_db
def test_deployment_demo_seeds_consistent_data_and_preserves_existing_accounts(seeded_module, client_for):
    passwords = {name: secrets.token_urlsafe(24) for name in USERNAMES}
    assert seed(passwords)
    assert not seed(passwords)
    with pytest.raises(CommandError, match="different credentials"):
        seed(passwords | {AGENT: secrets.token_urlsafe(24)})

    users = {user.username: user for user in UserInfo.objects.filter(username__in=USERNAMES)}
    assert all(user.check_password(passwords[name]) and not user.is_superuser for name, user in users.items())
    agent = users[AGENT]
    network_agent = users[NETWORK_AGENT]
    assert agent.dept_id != network_agent.dept_id
    assert {REQUESTER_ROLE} == TicketAccess.for_user(users[REQUESTER]).roles
    assert ADMIN_ROLE in TicketAccess.for_user(users[ADMIN]).roles
    assert AGENT_ROLE in TicketAccess.for_user(agent).roles
    assert AGENT_ROLE in TicketAccess.for_user(network_agent).roles
    assert has_permission(agent, "assign:TicketFlowTickets", "assignees:TicketFlowTickets")
    assert not has_permission(network_agent, "assign:TicketFlowTickets", "assignees:TicketFlowTickets")

    tickets = Ticket.objects.all()
    assert tickets.count() == 12
    assert set(tickets.values_list("status", flat=True)) == set(Status.values)
    assert set(tickets.values_list("priority", flat=True)) == set(Priority.values)
    assert set(tickets.values_list("department_id", flat=True)) == {agent.dept_id, network_agent.dept_id}
    for ticket in tickets:
        assert ticket.version == ticket.logs.count()
        if ticket.first_response_at:
            assert ticket.first_response_at == ticket.comments.get(visibility=Visibility.PUBLIC).created_time
            assert ticket.comments.filter(visibility=Visibility.INTERNAL).exists()

    articles = KnowledgeArticle.objects.all()
    assert articles.filter(status=ArticleStatus.PUBLISHED).count() == 2
    assert articles.filter(status=ArticleStatus.DRAFT, creator=agent, source_ticket__status=Status.CLOSED).count() == 1
    assert tickets.filter(status=Status.CLOSED, knowledge_article__isnull=True).exists()

    ticket = tickets.get(department_id=agent.dept_id, title="门户密码重置邮件未收到")
    response = client_for(agent).post(
        f"/api/tickets/{ticket.pk}/assign", {"assignee_id": agent.pk, "version": ticket.version}, format="json"
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["pk"] == str(ticket.pk)
    assert response.data["data"]["assignee_id"] == agent.pk


def test_deployment_demo_requires_opt_in(monkeypatch):
    monkeypatch.delenv("TICKETFLOW_DEMO", raising=False)
    with pytest.raises(CommandError, match="TICKETFLOW_DEMO=true"):
        main()
