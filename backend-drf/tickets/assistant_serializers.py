from typing import Any

from rest_framework import serializers

from common.core.serializers import BaseModelSerializer
from tickets.models import AssistantFeedback, AssistantMessage, AssistantSession, Category


class SessionTitleSerializer(serializers.Serializer):
    title = serializers.CharField(min_length=1, max_length=200)


class SessionCreateSerializer(SessionTitleSerializer):
    title = serializers.CharField(min_length=1, max_length=200, default="新对话")


class AssistantSessionSerializer(BaseModelSerializer):
    ignore_field_permission = True
    pk = serializers.UUIDField(read_only=True)
    ticket_id = serializers.UUIDField(read_only=True, allow_null=True)
    created_time = serializers.DateTimeField(format="iso-8601", read_only=True)
    updated_time = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = AssistantSession
        fields: tuple[str, ...] = ("pk", "title", "ticket_id", "created_time", "updated_time")
        read_only_fields: tuple[str, ...] = fields


class HandoffSessionSerializer(AssistantSessionSerializer):
    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    ticket_number = serializers.CharField(source="ticket.number", read_only=True, allow_null=True)

    class Meta(AssistantSessionSerializer.Meta):
        fields = (*AssistantSessionSerializer.Meta.fields, "user_id", "username", "ticket_number")
        read_only_fields = fields


class AssistantReferenceSerializer(serializers.Serializer):
    article_id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)


class AssistantExcerptSerializer(AssistantReferenceSerializer):
    excerpt = serializers.CharField(max_length=800, allow_blank=True)


class FeedbackInputSerializer(serializers.Serializer):
    vote = serializers.ChoiceField(choices=AssistantFeedback.Vote.choices)
    reason = serializers.ChoiceField(choices=AssistantFeedback.Reason.choices, default=None, allow_null=True)
    comment = serializers.CharField(max_length=300, default="", allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["vote"] == AssistantFeedback.Vote.UP:
            attrs.update(reason=None, comment="")
        return attrs


class AssistantFeedbackSerializer(BaseModelSerializer):
    ignore_field_permission = True
    vote = serializers.ChoiceField(choices=AssistantFeedback.Vote.choices, read_only=True)
    reason = serializers.ChoiceField(choices=AssistantFeedback.Reason.choices, read_only=True, allow_null=True)
    created_time = serializers.DateTimeField(format="iso-8601", read_only=True)
    updated_time = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = AssistantFeedback
        fields = ("vote", "reason", "comment", "created_time", "updated_time")
        read_only_fields = fields


class AssistantTranscriptMessageSerializer(BaseModelSerializer):
    ignore_field_permission = True
    pk = serializers.UUIDField(read_only=True)
    role = serializers.ChoiceField(choices=AssistantMessage.Role.choices, read_only=True)
    references = AssistantReferenceSerializer(many=True, read_only=True)
    status = serializers.ChoiceField(choices=AssistantMessage.Status.choices, read_only=True)
    user_message_id = serializers.UUIDField(read_only=True, allow_null=True)
    created_time = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = AssistantMessage
        fields: tuple[str, ...] = ("pk", "role", "content", "references", "status", "user_message_id", "created_time")
        read_only_fields: tuple[str, ...] = fields


class AssistantMessageSerializer(AssistantTranscriptMessageSerializer):
    feedback = AssistantFeedbackSerializer(read_only=True, allow_null=True)

    class Meta(AssistantTranscriptMessageSerializer.Meta):
        fields = (*AssistantTranscriptMessageSerializer.Meta.fields, "feedback")
        read_only_fields = fields


class DownvoteSerializer(serializers.Serializer):
    session = HandoffSessionSerializer(source="message.session")
    question = AssistantTranscriptMessageSerializer(source="message.user_message")
    answer = AssistantMessageSerializer(source="message")


class AssistantDateRangeSerializer(serializers.Serializer):
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("created_from"), attrs.get("created_to")
        if start is not None and end is not None and start > end:
            raise serializers.ValidationError({"created_to": "结束时间不能早于开始时间"})
        return attrs


class AssistantStatsSerializer(serializers.Serializer):
    sessions = serializers.IntegerField(min_value=0)
    questions = serializers.IntegerField(min_value=0)
    up = serializers.IntegerField(min_value=0)
    down = serializers.IntegerField(min_value=0)
    handoffs = serializers.IntegerField(min_value=0)


class QuestionInputSerializer(serializers.Serializer):
    message = serializers.CharField(min_length=1, max_length=4000)


class HistoryEntrySerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=AssistantMessage.Role.choices)
    content = serializers.CharField()


class AssistantContextSerializer(serializers.Serializer):
    history = HistoryEntrySerializer(many=True, max_length=10 * 2)
    categories = serializers.ListField(child=serializers.ChoiceField(choices=Category.choices))


class QuestionContextSerializer(AssistantContextSerializer):
    user_message_id = serializers.UUIDField()
    references = AssistantExcerptSerializer(many=True, max_length=5)


class AnswerInputSerializer(serializers.Serializer):
    user_message_id = serializers.UUIDField()
    content = serializers.CharField(max_length=20000, allow_blank=True, trim_whitespace=False)
    references = AssistantReferenceSerializer(many=True, max_length=5)
    status = serializers.ChoiceField(choices=AssistantMessage.Status.choices)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["status"] == AssistantMessage.Status.COMPLETE and not attrs["content"].strip():
            raise serializers.ValidationError({"content": "已完成的回答需要正文"})
        return attrs


class AnswerResultSerializer(serializers.Serializer):
    assistant_message_id = serializers.UUIDField()
