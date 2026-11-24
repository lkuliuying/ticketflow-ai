from uuid import uuid4

import pytest

from identity.models import UserRole
from tests.integration.tickets.test_ticket_services import race_twice
from tickets.assistant_services import record_answer
from tickets.models import AssistantMessage, AssistantSession, Ticket
from tickets.policy import REQUESTER_ROLE
from tickets.services import TicketConflict, create_ticket


@pytest.mark.django_db(transaction=True)
def test_concurrent_writeback_and_handoff_create_only_one_record(requester, support, details):
    requester.roles.add(UserRole.objects.get_or_create(code=REQUESTER_ROLE, defaults={"name": "员工"})[0])
    session = AssistantSession.objects.create(user=requester, title="并发验证")
    question = AssistantMessage.objects.create(session=session, role=AssistantMessage.Role.USER, content="VPN")
    replies = race_twice(lambda: record_answer(requester.pk, session.pk, question.pk, "已回复", [], "complete"))
    assert len(set(replies)) == 1
    assert session.messages.filter(role=AssistantMessage.Role.ASSISTANT).count() == 1

    def submit():
        try:
            return create_ticket(requester, str(uuid4()), details, assistant_session_id=session.pk)[0].pk
        except TicketConflict:
            return None

    results = race_twice(submit)
    session.refresh_from_db()
    assert results.count(None) == 1 and session.ticket_id in results
    assert Ticket.objects.count() == 1
