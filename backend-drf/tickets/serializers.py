from django.utils import timezone
from rest_framework import serializers

from common.core.serializers import BaseModelSerializer
from tickets.models import Category, Priority, Status, Ticket, Visibility
from tickets.services import SLA_WARNING


class AssigneeSerializer(serializers.Serializer):
    pk = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    nickname = serializers.CharField(read_only=True, allow_blank=True)
    department_name = serializers.CharField(source="dept.name", read_only=True, allow_null=True, help_text="技能组名称")


class TicketSerializer(BaseModelSerializer):
    serializer_choice_field = serializers.ChoiceField
    pk = serializers.UUIDField(read_only=True)
    submitter_id = serializers.IntegerField(read_only=True)
    assignee_id = serializers.IntegerField(read_only=True, allow_null=True)
    department_id = serializers.UUIDField(read_only=True, help_text="技能组 ID")
    submitter_name = serializers.CharField(source="submitter.username", read_only=True)
    assignee_name = serializers.CharField(source="assignee.username", read_only=True, allow_null=True)
    department_name = serializers.CharField(source="department.name", read_only=True, help_text="技能组名称")
    sla_state = serializers.SerializerMethodField()
    sla_due_at = serializers.DateTimeField(format="iso-8601", read_only=True)
    first_response_at = serializers.DateTimeField(format="iso-8601", read_only=True, allow_null=True)
    resolved_at = serializers.DateTimeField(format="iso-8601", read_only=True, allow_null=True)
    created_time = serializers.DateTimeField(format="iso-8601", read_only=True)
    updated_time = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = Ticket
        fields: tuple[str, ...] = (
            "pk",
            "number",
            "title",
            "description",
            "category",
            "priority",
            "status",
            "submitter_id",
            "submitter_name",
            "assignee_id",
            "assignee_name",
            "department_id",
            "department_name",
            "sla_due_at",
            "sla_state",
            "first_response_at",
            "resolved_at",
            "ai_summary",
            "ai_tags",
            "version",
            "created_time",
            "updated_time",
        )
        read_only_fields: tuple[str, ...] = fields
        table_fields = ("number", "title", "category", "priority", "status", "assignee_name", "sla_due_at", "sla_state")

    def get_sla_state(self, ticket: Ticket) -> str:
        if ticket.resolved_at is not None:
            return "MET" if ticket.resolved_at <= ticket.sla_due_at else "OVERDUE"
        now = self.context.get("now", timezone.now())
        if ticket.sla_due_at <= now:
            return "OVERDUE"
        return "DUE_SOON" if ticket.sla_due_at <= now + SLA_WARNING else "ON_TRACK"


class TicketCreateSerializer(BaseModelSerializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=20000)
    category = serializers.ChoiceField(choices=Category.choices)
    priority = serializers.ChoiceField(choices=Priority.choices)

    class Meta:
        model = Ticket
        fields = ("title", "description", "category", "priority")


class TicketColumnsSerializer(TicketSerializer):
    class Meta(TicketSerializer.Meta):
        read_only_fields = tuple(
            name for name in TicketSerializer.Meta.fields if name not in TicketCreateSerializer.Meta.fields
        )


class TransitionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    target_status = serializers.ChoiceField(choices=Status.choices)
    note = serializers.CharField(max_length=4000, required=False, allow_blank=True)


class AssignmentSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    assignee_id = serializers.IntegerField(min_value=1, allow_null=True)


class AssignmentReturnSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)
    visibility = serializers.ChoiceField(choices=Visibility.choices)


class SuggestionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    summary = serializers.CharField(max_length=4000)
    tags = serializers.ListField(child=serializers.CharField(max_length=64), max_length=12)
    category = serializers.ChoiceField(choices=Category.choices, required=False)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
