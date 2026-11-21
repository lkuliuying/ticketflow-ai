from drf_spectacular.utils import extend_schema_serializer, inline_serializer
from rest_framework import serializers

from tickets.serializers import TicketSerializer


def envelope(name: str, data: serializers.Field) -> serializers.Serializer:
    """声明 ApiResponse 的外层结构和业务数据。"""
    result = inline_serializer(
        name=name,
        fields={
            "code": serializers.IntegerField(),
            "detail": serializers.CharField(),
            "requestId": serializers.CharField(),
            "timestamp": serializers.CharField(),
            "data": data,
        },
    )
    extend_schema_serializer(many=False)(type(result))
    return result


def page(name: str, items: serializers.Field) -> serializers.Serializer:
    return inline_serializer(name=name, fields={"total": serializers.IntegerField(), "results": items})


class TimelineEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    created_time = serializers.DateTimeField(format="iso-8601")
    kind = serializers.ChoiceField(choices=["log", "comment"])
    actor = serializers.CharField()
    body = serializers.CharField(allow_blank=True)
    action = serializers.CharField(allow_blank=True)
    from_status = serializers.CharField(allow_null=True)
    to_status = serializers.CharField(allow_null=True)
    visibility = serializers.CharField(allow_blank=True)


class TicketDetailSerializer(TicketSerializer):
    available_transitions = serializers.ListField(child=serializers.CharField(), read_only=True)
    timeline = page("TicketTimelinePage", TimelineEntrySerializer(many=True))

    class Meta(TicketSerializer.Meta):
        fields = (*TicketSerializer.Meta.fields, "available_transitions", "timeline")


ticket_result = envelope("TicketResult", TicketSerializer())
ticket_detail_result = envelope("TicketDetailResult", TicketDetailSerializer())
ticket_list_result = envelope("TicketListResult", page("TicketPage", TicketSerializer(many=True)))
timeline_result = envelope("TicketTimelineResult", page("TicketTimelinePage", TimelineEntrySerializer(many=True)))


class CommentResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    author_id = serializers.IntegerField()
    body = serializers.CharField()
    visibility = serializers.CharField()
    created_time = serializers.DateTimeField(format="iso-8601")


comment_result = envelope("TicketCommentResult", CommentResultSerializer())
dashboard_result = envelope(
    "TicketDashboardResult",
    inline_serializer(
        name="TicketDashboard",
        fields={key: serializers.DictField(child=serializers.IntegerField()) for key in ("status", "priority", "sla")},
    ),
)
