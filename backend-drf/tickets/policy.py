from dataclasses import dataclass
from typing import cast
from uuid import UUID

from django.db.models import Q, QuerySet

from common.core.permission import get_user_permission_codes
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


def has_permission(user: UserInfo, code: str, *additional_codes: str) -> bool:
    return user.is_superuser or {code, *additional_codes} <= get_user_permission_codes(user)


def assignment_candidates(access: "TicketAccess") -> QuerySet[UserInfo]:
    roles = (AGENT_ROLE, ADMIN_ROLE)
    eligible = (
        Q(is_superuser=True)
        | Q(roles__code__in=roles, roles__is_active=True)
        | Q(dept__roles__code__in=roles, dept__roles__is_active=True)
    )
    queryset = UserInfo.objects.filter(eligible, is_active=True)
    if not access.admin:
        if access.department_id is None:
            return queryset.none()
        queryset = queryset.filter(dept_id=access.department_id)
    return queryset.select_related("dept").distinct().order_by("username", "pk")


@dataclass(frozen=True)
class TicketAccess:
    user_id: int
    department_id: UUID | None
    roles: frozenset[str]
    is_superuser: bool

    @classmethod
    def for_user(cls, user: UserInfo) -> "TicketAccess":
        roles = set(user.roles.filter(is_active=True).values_list("code", flat=True))
        if user.dept_id is not None:
            roles.update(user.dept.roles.filter(is_active=True).values_list("code", flat=True))
        return cls(user.pk, user.dept_id, frozenset(roles), user.is_superuser)

    @property
    def agent(self) -> bool:
        return AGENT_ROLE in self.roles

    @property
    def admin(self) -> bool:
        return self.is_superuser or ADMIN_ROLE in self.roles

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

    def can_reply(self, ticket: Ticket) -> bool:
        return self.user_id == ticket.submitter_id or self.can_handle(ticket)

    def targets(self, ticket: Ticket) -> tuple[str, ...]:
        allowed = self.can_handle(ticket)
        if ticket.status in VERIFY_STATES:
            allowed = self.admin or ticket.submitter_id == self.user_id
        return TRANSITIONS.get(ticket.status, ()) if allowed else ()
