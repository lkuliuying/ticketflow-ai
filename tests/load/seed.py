"""Seed deterministic IDs, representative timelines and separate AI load identities."""

import json
import os
import sys
from datetime import timedelta

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from fixtures import AGENT_COUNT, TICKET_COUNT, TITLE_PREFIX, agent_name, ticket_id
from identity.models import UserInfo, UserRole
from ops.seed_ticketflow_demo import AGENT, REQUESTER, USERNAMES, seed
from tickets.cache import invalidate_dashboard
from tickets.models import Category, Priority, Status, Ticket, TicketComment, TicketLog, Visibility
from tickets.policy import AGENT_ROLE


def seed_agents(passwords, handler) -> None:
    role = UserRole.objects.get(code=AGENT_ROLE)
    for index in range(AGENT_COUNT):
        username = agent_name(index)
        user = UserInfo.objects.filter(username=username).first()
        password = passwords[username]
        if user is None:
            user = UserInfo.objects.create_user(
                username=username,
                password=password,
                dept=handler.dept,
                date_password_updated=timezone.now(),
            )
            user.roles.add(role)
        elif not user.check_password(password):
            raise CommandError(f"Restore original credentials for {username}")


def seed_tickets(requester, handler) -> None:
    scoped = Ticket.objects.filter(title__startswith=TITLE_PREFIX)
    count = scoped.count()
    if count == TICKET_COUNT:
        return
    if count:
        raise CommandError(f"Expected an empty load dataset or {TICKET_COUNT} tickets, found {count}")
    now = timezone.now()
    priorities = tuple(Priority.values)
    for start in range(0, TICKET_COUNT, 500):
        tickets, logs, comments = [], [], []
        for index in range(start, min(start + 500, TICKET_COUNT)):
            pk = ticket_id(index)
            assigned = index % 5 != 4
            status = Status.IN_PROGRESS if assigned else Status.OPEN
            tickets.append(
                Ticket(
                    id=pk,
                    number=f"TF-{pk.hex.upper()}",
                    title=f"{TITLE_PREFIX} {index:05d}",
                    description=f"Account access case {index:05d} with an intermittently unavailable portal.",
                    category=Category.ACCOUNT,
                    priority=priorities[index % len(priorities)],
                    status=status,
                    submitter=requester,
                    assignee=handler if assigned else None,
                    department=handler.dept,
                    dept_belong=handler.dept,
                    creator=requester,
                    modifier=handler if assigned else requester,
                    sla_due_at=now + timedelta(days=1 + index % 4),
                    first_response_at=now if assigned else None,
                    version=3 if assigned else 1,
                )
            )
            logs.append(TicketLog(ticket_id=pk, action="CREATE", to_status=Status.OPEN, operator=requester))
            if assigned:
                logs.extend(
                    (
                        TicketLog(
                            ticket_id=pk, action="ASSIGN", to_status=Status.OPEN, operator=handler, internal=True
                        ),
                        TicketLog(
                            ticket_id=pk,
                            action="TRANSITION",
                            from_status=Status.OPEN,
                            to_status=Status.IN_PROGRESS,
                            operator=handler,
                        ),
                    )
                )
                comments.extend(
                    TicketComment(
                        ticket_id=pk,
                        author=handler,
                        body=f"Timeline fixture {step + 1}",
                        visibility=Visibility.PUBLIC if step % 2 == 0 else Visibility.INTERNAL,
                    )
                    for step in range(8 if index == 0 else 2)
                )
        Ticket.objects.bulk_create(tickets)
        TicketLog.objects.bulk_create(logs)
        TicketComment.objects.bulk_create(comments)
    transaction.on_commit(invalidate_dashboard)


@transaction.atomic
def main() -> None:
    if os.environ.get("TICKETFLOW_DEMO") != "true" or os.environ.get("TICKETFLOW_LOAD_FIXTURES") != "true":
        raise CommandError("Use the isolated demo load overlay to seed these fixtures")
    passwords = json.load(sys.stdin)
    seed({name: passwords[name] for name in USERNAMES})
    handler = UserInfo.objects.get(username=AGENT)
    seed_agents(passwords, handler)
    seed_tickets(UserInfo.objects.get(username=REQUESTER), handler)
    print(f"Ready: {TICKET_COUNT} load tickets and {AGENT_COUNT} load agents; detail={ticket_id(0)}")
