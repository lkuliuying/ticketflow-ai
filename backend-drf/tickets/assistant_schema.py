from typing import Any

from drf_spectacular.extensions import OpenApiSerializerExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import Direction, OpenApiParameter, OpenApiTypes, inline_serializer

from tickets.api_schema import envelope, page, ticket_error_result
from tickets.assistant_serializers import (
    AnswerResultSerializer,
    AssistantContextSerializer,
    AssistantFeedbackSerializer,
    AssistantMessageSerializer,
    AssistantSessionSerializer,
    AssistantStatsSerializer,
    AssistantTranscriptMessageSerializer,
    DownvoteSerializer,
    HandoffSessionSerializer,
    QuestionContextSerializer,
    SessionTitleSerializer,
)


class SessionTitleSchema(OpenApiSerializerExtension):
    target_class = SessionTitleSerializer

    def map_serializer(self, auto_schema: AutoSchema, direction: Direction) -> dict[str, Any]:
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        # Renaming always requires a title, even for this PATCH action.
        schema["required"] = ["title"]
        return schema


page_parameters = [OpenApiParameter("page", int), OpenApiParameter("size", int)]
date_parameters = [
    OpenApiParameter("created_from", OpenApiTypes.DATETIME, description="开始时间（含）"),
    OpenApiParameter("created_to", OpenApiTypes.DATETIME, description="结束时间（含）"),
]
assistant_errors = dict.fromkeys((400, 401, 403, 404), ticket_error_result)
internal_errors = {**assistant_errors, 429: ticket_error_result, 503: ticket_error_result}

session_result = envelope("AssistantSessionResult", AssistantSessionSerializer())
session_list_result = envelope(
    "AssistantSessionListResult", page("AssistantSessionPage", AssistantSessionSerializer(many=True))
)
message_list_result = envelope(
    "AssistantMessageListResult", page("AssistantMessagePage", AssistantMessageSerializer(many=True))
)
feedback_result = envelope("AssistantFeedbackResult", AssistantFeedbackSerializer())
downvote_list_result = envelope(
    "AssistantDownvoteListResult", page("AssistantDownvotePage", DownvoteSerializer(many=True))
)
handoff_list_result = envelope(
    "AssistantHandoffListResult", page("AssistantHandoffPage", HandoffSessionSerializer(many=True))
)
stats_result = envelope("AssistantStatsResult", AssistantStatsSerializer())
context_result = envelope("AssistantContextResult", AssistantContextSerializer())
question_result = envelope("AssistantQuestionResult", QuestionContextSerializer())
answer_result = envelope("AssistantAnswerResult", AnswerResultSerializer())
ticket_session_result = envelope(
    "TicketAssistantSessionResult",
    inline_serializer(
        name="TicketAssistantSession",
        fields={
            "session": AssistantSessionSerializer(),
            "messages": page("AssistantTranscriptPage", AssistantTranscriptMessageSerializer(many=True)),
        },
    ),
)
