import django_filters as filters
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from tickets.models import Category, Priority, Status, Ticket
from tickets.services import SLA_WARNING


class TicketFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Status.choices)
    priority = filters.ChoiceFilter(choices=Priority.choices)
    category = filters.ChoiceFilter(choices=Category.choices)
    assignee_id = filters.NumberFilter()
    department_id = filters.UUIDFilter()
    sla = filters.ChoiceFilter(
        choices=[(state, state) for state in ("ON_TRACK", "DUE_SOON", "OVERDUE", "MET")],
        method="filter_sla",
    )
    q = filters.CharFilter(method="filter_q", max_length=200)

    class Meta:
        model = Ticket
        fields = ("status", "priority", "category", "assignee_id", "department_id", "sla", "q")

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
