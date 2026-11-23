from rest_framework import serializers

from common.core.serializers import BaseModelSerializer
from tickets.models import RatingTag, TicketRating


class RatingInputSerializer(serializers.Serializer):
    resolved = serializers.BooleanField()
    satisfaction = serializers.IntegerField(min_value=1, max_value=5)
    handler_score = serializers.IntegerField(min_value=1, max_value=5)
    tags = serializers.ListField(
        child=serializers.ChoiceField(choices=RatingTag.choices), max_length=len(RatingTag), required=False
    )
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)

    def validate_comment(self, comment: str | None) -> str | None:
        return comment or None

    def validate_tags(self, tags: list[str]) -> list[str]:
        if len(set(tags)) != len(tags):
            raise serializers.ValidationError("评价标签不能重复")
        return tags


class TicketRatingSerializer(BaseModelSerializer):
    pk = serializers.UUIDField(read_only=True, label="编号")
    ticket_id = serializers.UUIDField(read_only=True, label="工单 ID")
    ticket_number = serializers.CharField(source="ticket.number", read_only=True, label="工单号")
    rater_id = serializers.IntegerField(read_only=True, label="评价人 ID")
    rater_name = serializers.CharField(source="rater.username", read_only=True, label="评价人")
    handler_id = serializers.IntegerField(read_only=True, allow_null=True, label="处理人 ID")
    handler_name = serializers.CharField(source="handler.username", read_only=True, allow_null=True, label="被评处理人")
    satisfaction = serializers.IntegerField(min_value=1, max_value=5, read_only=True, label="满意度")
    handler_score = serializers.IntegerField(min_value=1, max_value=5, read_only=True, label="处理人评分")
    tags = serializers.ListField(child=serializers.ChoiceField(choices=RatingTag.choices), read_only=True, label="标签")
    created_time = serializers.DateTimeField(format="iso-8601", read_only=True, label="评价时间")

    class Meta:
        model = TicketRating
        table_fields = (
            "ticket_number",
            "rater_name",
            "handler_name",
            "resolved",
            "satisfaction",
            "handler_score",
            "tags",
            "comment",
            "created_time",
        )
        fields = ("pk", "ticket_id", "rater_id", "handler_id", *table_fields)
        read_only_fields = fields


class RatingMetricsSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    avg_satisfaction = serializers.FloatField(min_value=1, max_value=5, allow_null=True)
    avg_handler_score = serializers.FloatField(min_value=1, max_value=5, allow_null=True)
    resolved_rate = serializers.FloatField(
        min_value=0, max_value=1, allow_null=True, help_text="已解决数除以评价总数，无评价时为 null。"
    )
    tags = serializers.DictField(child=serializers.IntegerField(min_value=1), help_text="各已出现标签的次数。")


class RatingHandlerMetricsSerializer(RatingMetricsSerializer):
    handler_id = serializers.IntegerField(allow_null=True)
    handler_name = serializers.CharField(allow_null=True)


class RatingSummarySerializer(RatingMetricsSerializer):
    by_handler = RatingHandlerMetricsSerializer(
        many=True, required=False, help_text="仅管理员返回，未关联处理人的评价归入 handler_id 为 null 的组。"
    )
