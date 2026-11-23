from drf_spectacular.utils import extend_schema_serializer, inline_serializer
from rest_framework import serializers

from tickets.rating_serializers import RatingSummarySerializer, TicketRatingSerializer
from tickets.serializers import AssigneeSerializer, TicketSerializer


def envelope(name: str, data: serializers.Field | None = None) -> serializers.Serializer:
    """声明 ApiResponse 的外层结构和业务数据。"""
    fields: dict[str, serializers.Field] = {
        "code": serializers.IntegerField(),
        "detail": serializers.CharField(),
        "requestId": serializers.CharField(),
        "timestamp": serializers.CharField(),
    }
    if data is not None:
        fields["data"] = data
    result = inline_serializer(name=name, fields=fields)
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


class TicketViewerSerializer(serializers.Serializer):
    can_handle = serializers.BooleanField()
    can_assign = serializers.BooleanField(help_text="管理员对未关闭工单同时持有指派和候选人权限时可用。")
    can_reply = serializers.BooleanField(
        help_text="持有 comments:TicketFlowTickets 菜单权限，且可处理工单或为工单提交人时可对外回复。"
        "超级用户免菜单权限检查。工单状态和提交人的历史处理身份不影响此能力。"
    )
    can_comment_internal = serializers.BooleanField(
        help_text="持有 comments:TicketFlowTickets 菜单权限且可处理工单时可写内部备注。超级用户免菜单权限检查。"
    )
    can_archive = serializers.BooleanField(
        help_text="已关闭且尚未转存时，管理员或当前及历史技术员持有知识库创建权限即可转存。"
    )
    can_return = serializers.BooleanField(help_text="仅持有退回权限的当前技术员可退回未关闭工单。")
    can_rate = serializers.BooleanField(help_text="持有评价权限的工单提交人可对已关闭且尚未评价的工单提交评价。")
    read_only = serializers.BooleanField(
        help_text="技术员曾经处理但当前未指派给自己时为 true，时间线包含内部内容。"
        "提交人的 can_reply 和 available_transitions，以及转存能力 can_archive，按各自规则给出。"
    )


class TicketDetailSerializer(TicketSerializer):
    viewer = TicketViewerSerializer(read_only=True)
    rating = TicketRatingSerializer(
        read_only=True, allow_null=True, help_text="仅评价人、评价记录中的处理人和管理员可见，其他情况为 null。"
    )
    available_transitions = serializers.ListField(
        child=serializers.CharField(), read_only=True, help_text="提交人的验收或重开动作在历史只读时仍可用。"
    )
    timeline = page("TicketTimelinePage", TimelineEntrySerializer(many=True))

    class Meta(TicketSerializer.Meta):
        fields = (*TicketSerializer.Meta.fields, "viewer", "available_transitions", "timeline", "rating")


ticket_result = envelope("TicketResult", TicketSerializer())
ticket_error_result = envelope("TicketErrorResult")
assignees_result = envelope("TicketAssigneesResult", AssigneeSerializer(many=True))
ticket_detail_result = envelope("TicketDetailResult", TicketDetailSerializer())
ticket_list_result = envelope("TicketListResult", page("TicketPage", TicketSerializer(many=True)))
timeline_result = envelope("TicketTimelineResult", page("TicketTimelinePage", TimelineEntrySerializer(many=True)))
rating_result = envelope("TicketRatingResult", TicketRatingSerializer())
rating_list_result = envelope("TicketRatingListResult", page("TicketRatingPage", TicketRatingSerializer(many=True)))
rating_summary_result = envelope("TicketRatingSummaryResult", RatingSummarySerializer())


class CommentResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    author_id = serializers.IntegerField()
    body = serializers.CharField()
    visibility = serializers.CharField()
    created_time = serializers.DateTimeField(format="iso-8601")


comment_result = envelope("TicketCommentResult", CommentResultSerializer())


class DashboardAssignmentSerializer(serializers.Serializer):
    unassigned = serializers.IntegerField(required=False, min_value=0, help_text="管理员的待分配工单数")
    current = serializers.IntegerField(required=False, min_value=0, help_text="当前指派给技术员的工单数")
    history = serializers.IntegerField(required=False, min_value=0, help_text="技术员曾经处理的工单数")


dashboard_result = envelope(
    "TicketDashboardResult",
    inline_serializer(
        name="TicketDashboard",
        fields={
            **{key: serializers.DictField(child=serializers.IntegerField()) for key in ("status", "priority", "sla")},
            "assignment": DashboardAssignmentSerializer(help_text="计数应用当前筛选。普通员工返回空对象。"),
        },
    ),
)
