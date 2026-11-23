from dataclasses import dataclass
from typing import cast

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from common.core.permission import get_user_permission_codes
from identity.models import UserInfo
from tickets.models import Status, Ticket, TicketAssignment

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


def assignment_candidates() -> QuerySet[UserInfo]:
    eligible = Q(roles__code=AGENT_ROLE, roles__is_active=True, roles__deleted_at__isnull=True) | Q(
        dept__roles__code=AGENT_ROLE, dept__roles__is_active=True, dept__roles__deleted_at__isnull=True
    )
    return (
        UserInfo.objects.filter(eligible, is_active=True, is_superuser=False, dept__is_active=True)
        .filter(Q(date_expired__isnull=True) | Q(date_expired__gt=timezone.now()))
        .exclude(invite_status=UserInfo.InviteStatusChoices.PENDING)
        .select_related("dept")
        .distinct()
        .order_by("username", "pk")
    )


@dataclass(frozen=True)
class TicketAccess:
    user_id: int
    roles: frozenset[str]
    is_superuser: bool

    @classmethod
    def for_user(cls, user: UserInfo) -> "TicketAccess":
        roles = set(user.roles.filter(is_active=True).values_list("code", flat=True))
        if user.dept_id is not None:
            roles.update(user.dept.roles.filter(is_active=True).values_list("code", flat=True))
        return cls(user.pk, frozenset(roles), user.is_superuser)

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
            allowed |= Q(assignee_id=self.user_id) | Q(self.history())
        return queryset.filter(allowed)

    def history(self) -> Exists:
        return Exists(TicketAssignment.objects.filter(ticket_id=OuterRef("pk"), assignee_id=self.user_id))

    def assignment_filter(self, queryset: QuerySet[Ticket], assignment: str) -> QuerySet[Ticket]:
        if assignment == "unassigned":
            return (
                queryset.filter(assignee__isnull=True).exclude(status=Status.CLOSED) if self.admin else queryset.none()
            )
        if assignment == "current":
            return queryset.filter(assignee_id=self.user_id)
        if assignment == "history":
            return queryset.filter(self.history()).exclude(assignee_id=self.user_id)
        return queryset

    def read_only(self, ticket: Ticket) -> bool:
        return (
            not self.admin
            and self.agent
            and ticket.assignee_id != self.user_id
            and TicketAssignment.objects.filter(ticket=ticket, assignee_id=self.user_id).exists()
        )

    def can_handle(self, ticket: Ticket) -> bool:
        return self.admin or (self.agent and ticket.assignee_id == self.user_id)

    def can_return(self, ticket: Ticket) -> bool:
        return not self.admin and self.can_handle(ticket) and ticket.status != Status.CLOSED

    def can_archive(self, ticket: Ticket) -> bool:
        return self.can_handle(ticket) or self.read_only(ticket)

    def can_reply(self, ticket: Ticket) -> bool:
        return self.can_handle(ticket) or (self.user_id == ticket.submitter_id and not self.read_only(ticket))

    def targets(self, ticket: Ticket) -> tuple[str, ...]:
        allowed = self.can_handle(ticket)
        if ticket.status in VERIFY_STATES:
            allowed = self.admin or (ticket.submitter_id == self.user_id and not self.read_only(ticket))
        return TRANSITIONS.get(ticket.status, ()) if allowed else ()
