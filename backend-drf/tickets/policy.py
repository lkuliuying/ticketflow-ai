from dataclasses import dataclass
from typing import cast
from uuid import UUID

from django.db.models import Q, QuerySet

from identity.models import UserInfo
from tickets.models import Status, Ticket

REQUESTER_ROLE = "ticketflow_requester"
AGENT_ROLE = "ticketflow_agent"
ADMIN_ROLE = "ticketflow_admin"

TRANSITIONS = cast(
    "dict[str, tuple[str, ...]]",
    {
        Status.OPEN: (Status.IN_PROGRESS,),
        Status.IN_PROGRESS: (Status.PENDING_VERIFY,),
        Status.PENDING_VERIFY: (Status.CLOSED, Status.IN_PROGRESS),
        Status.CLOSED: (Status.REOPENED,),
        Status.REOPENED: (Status.IN_PROGRESS,),
    },
)
VERIFY_STATES = (Status.PENDING_VERIFY, Status.CLOSED)


@dataclass(frozen=True)
class TicketAccess:
    user_id: int
    department_id: UUID | None
    agent: bool
    admin: bool

    @classmethod
    def for_user(cls, user: UserInfo) -> "TicketAccess":
        roles = set(user.roles.filter(is_active=True).values_list("code", flat=True))
        if user.dept_id is not None:
            roles.update(user.dept.roles.filter(is_active=True).values_list("code", flat=True))
        return cls(user.pk, user.dept_id, AGENT_ROLE in roles, user.is_superuser or ADMIN_ROLE in roles)

    def scope(self, queryset: QuerySet[Ticket]) -> QuerySet[Ticket]:
        if self.admin:
            return queryset
        allowed = Q(submitter_id=self.user_id)
        if self.agent:
            allowed |= Q(assignee_id=self.user_id)
            if self.department_id is not None:
                allowed |= Q(department_id=self.department_id)
        return queryset.filter(allowed)

    def can_handle(self, ticket: Ticket) -> bool:
        return self.admin or (
            self.agent and (ticket.assignee_id == self.user_id or ticket.department_id == self.department_id)
        )

    def targets(self, ticket: Ticket) -> tuple[str, ...]:
        allowed = self.can_handle(ticket)
        if ticket.status in VERIFY_STATES:
            allowed = self.admin or ticket.submitter_id == self.user_id
        return TRANSITIONS.get(ticket.status, ()) if allowed else ()
