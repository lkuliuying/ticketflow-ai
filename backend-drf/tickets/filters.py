import django_filters as filters
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from tickets.models import Category, Priority, Status, Ticket
from tickets.policy import TicketAccess
from tickets.services import SLA_WARNING


class TicketFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Status.choices)
    priority = filters.ChoiceFilter(choices=Priority.choices)
    category = filters.ChoiceFilter(choices=Category.choices)
    assignee_id = filters.NumberFilter(label="处理人")
    department_id = filters.UUIDFilter(label="所属技能组")
    assignment = filters.ChoiceFilter(
        label="指派状态",
        choices=[("unassigned", "待分配"), ("current", "当前处理"), ("history", "历史处理")],
        method="filter_assignment",
        help_text="unassigned 为管理员的未关闭且未指派工单，current 为当前指派给本人，history 为曾指派给本人。",
    )
    sla = filters.ChoiceFilter(
        label="SLA 状态",
        choices=[("ON_TRACK", "正常"), ("DUE_SOON", "即将超时"), ("OVERDUE", "已超时"), ("MET", "按时完成")],
        method="filter_sla",
    )
    q = filters.CharFilter(label="关键字", method="filter_q", max_length=200)

    class Meta:
        model = Ticket
        fields = ("status", "priority", "category", "assignee_id", "department_id", "assignment", "sla", "q")

    def filter_assignment(self, queryset: QuerySet[Ticket], name: str, value: str) -> QuerySet[Ticket]:
        # 异步导出重放视图时，任务请求携带执行时重新加载的提交者。
        user = getattr(self.request, "user", None)
        if user is None or not user.is_authenticated:
            return queryset.none()
        return TicketAccess.for_user(user).assignment_filter(queryset, value)

    def filter_sla(self, queryset: QuerySet[Ticket], name: str, state: str) -> QuerySet[Ticket]:
        now = timezone.now()
        active = Q(resolved_at__isnull=True)
        return queryset.filter(
            {
                "ON_TRACK": active & Q(sla_due_at__gt=now + SLA_WARNING),
                "DUE_SOON": active & Q(sla_due_at__gt=now, sla_due_at__lte=now + SLA_WARNING),
                "OVERDUE": (active & Q(sla_due_at__lte=now)) | Q(resolved_at__gt=F("sla_due_at")),
                "MET": Q(resolved_at__lte=F("sla_due_at")),
            }[state]
        )

    def filter_q(self, queryset: QuerySet[Ticket], name: str, value: str) -> QuerySet[Ticket]:
        return queryset.filter(Q(number__icontains=value) | Q(title__icontains=value))
