from django.db.models import Count, F, Max, OuterRef, Subquery
from django.utils import timezone

from identity.models import DeptInfo, UserInfo
from tickets.models import Status, Ticket, TicketAssignment, TicketLog
from tickets.policy import assignment_candidates


def end_assignment(ticket: Ticket, reason: str, note: str = "") -> None:
    TicketAssignment.objects.filter(ticket=ticket, ended_at__isnull=True).update(
        ended_at=timezone.now(), end_reason=reason, note=note
    )


def set_assignee(ticket: Ticket, assignee_id: int | None, actor: UserInfo | None) -> None:
    if (
        ticket.assignee_id == assignee_id
        and TicketAssignment.objects.filter(ticket=ticket, ended_at__isnull=True).exists()
    ):
        return
    end_assignment(ticket, str(TicketAssignment.EndReason.REASSIGNED))
    ticket.assignee_id = assignee_id
    if assignee_id is not None:
        TicketAssignment.objects.create(
            ticket=ticket, assignee_id=assignee_id, assigned_by=actor, started_at=timezone.now()
        )


def dispatch(ticket: Ticket, *, reopening: bool = False) -> None:
    """Choose and record a system assignment inside the caller's transaction."""
    # 与技能组外键所需的 KEY SHARE 锁兼容，且同组派单必须等上一事务提交。
    department = DeptInfo.objects.select_for_update(no_key=True).get(pk=ticket.department_id)
    candidates = assignment_candidates().filter(dept=department)
    assignee_id = None
    if reopening:
        previous = ticket.assignee_id or (
            ticket.assignments.order_by("-started_at", "-id").values_list("assignee_id", flat=True).first()
        )
        if previous is not None:
            assignee_id = candidates.filter(pk=previous).values_list("pk", flat=True).first()
    if assignee_id is None:
        workload = (
            Ticket.objects.filter(assignee_id=OuterRef("pk"))
            .exclude(status=Status.CLOSED)
            .order_by()
            .values("assignee_id")
            .annotate(total=Count("pk"))
            .values("total")
        )
        last_assignment = (
            TicketAssignment.objects.filter(assignee_id=OuterRef("pk"))
            .values("assignee_id")
            .annotate(latest=Max("started_at"))
            .values("latest")
        )
        assignee_id = (
            candidates.exclude(pk=ticket.submitter_id)
            .annotate(workload=Subquery(workload), last_assignment=Subquery(last_assignment))
            .order_by(F("workload").asc(nulls_first=True), F("last_assignment").asc(nulls_first=True), "username")
            .values_list("pk", flat=True)
            .first()
        )
    set_assignee(ticket, assignee_id, None)
    if assignee_id is not None:
        TicketLog.objects.create(
            ticket=ticket,
            action="REOPEN_ASSIGN" if reopening else "AUTO_ASSIGN",
            to_status=ticket.status,
            note=f"处理人：{ticket.assignee.username}",
            internal=True,
        )
