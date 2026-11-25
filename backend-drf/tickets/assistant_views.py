from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.urls.converters import UUIDConverter
from django.utils.functional import cached_property
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.viewsets import GenericViewSet

from common.core.modelset.base import BaseViewSet
from common.core.response import ApiResponse
from tickets import assistant_schema as schema
from tickets import assistant_services as services
from tickets.assistant_serializers import (
    AnswerInputSerializer,
    AssistantDateRangeSerializer,
    AssistantFeedbackSerializer,
    AssistantMessageSerializer,
    AssistantSessionSerializer,
    DownvoteSerializer,
    FeedbackInputSerializer,
    HandoffSessionSerializer,
    QuestionInputSerializer,
    SessionCreateSerializer,
    SessionTitleSerializer,
)
from tickets.cache import check_rate
from tickets.internal_auth import InternalServiceUserAuthentication, verify_internal_request
from tickets.models import AssistantFeedback, AssistantSession
from tickets.policy import TicketAccess

internal_headers = [OpenApiParameter("Retry-After", int, OpenApiParameter.HEADER, response=[429])]
session_id_parameter = OpenApiParameter("id", UUID, OpenApiParameter.PATH, description="会话 UUID")


class AssistantViewSet(BaseViewSet, GenericViewSet):
    lookup_value_regex = UUIDConverter.regex

    @cached_property
    def access(self) -> TicketAccess:
        return TicketAccess.for_user(self.request.user)

    def _page(self, queryset: QuerySet, serializer_class: type) -> ApiResponse:
        rows = self.paginate_queryset(queryset)
        data = serializer_class(rows, many=True).data
        return ApiResponse(data=self.get_paginated_response(data).data)


class EmployeeAssistantViewSet(AssistantViewSet):
    """员工 AI 助手"""

    serializer_class = AssistantSessionSerializer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        services.require_employee(self.access)


class AssistantSessionViewSet(EmployeeAssistantViewSet):
    """助手会话"""

    @extend_schema(
        parameters=schema.page_parameters, responses={200: schema.session_list_result, **schema.assistant_errors}
    )
    def list(self, request: Request) -> ApiResponse:
        """助手会话列表"""
        return self._page(AssistantSession.objects.filter(user_id=self.access.user_id), AssistantSessionSerializer)

    @extend_schema(request=SessionCreateSerializer, responses={201: schema.session_result, **schema.assistant_errors})
    def create(self, request: Request) -> ApiResponse:
        """新建助手会话"""
        serializer = SessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AssistantSession.objects.create(user_id=self.access.user_id, **serializer.validated_data)
        return ApiResponse(data=AssistantSessionSerializer(session).data, status=201)

    @extend_schema(
        description="请求必须提供 title。",
        parameters=[session_id_parameter],
        request=SessionTitleSerializer,
        responses={200: schema.session_result, **schema.assistant_errors},
    )
    @transaction.atomic
    def partial_update(self, request: Request, pk: UUID) -> ApiResponse:
        """修改会话标题"""
        session = services.owned_session(self.access.user_id, pk, lock=True)
        serializer = SessionTitleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session.title = serializer.validated_data["title"]
        session.save(update_fields=["title", "updated_time"])
        return ApiResponse(data=AssistantSessionSerializer(session).data)

    @extend_schema(parameters=[session_id_parameter], responses={204: None, **schema.assistant_errors})
    @transaction.atomic
    def destroy(self, request: Request, pk: UUID) -> Response:
        """删除助手会话"""
        services.owned_session(self.access.user_id, pk, lock=True).delete()
        return Response(status=204)

    @extend_schema(
        parameters=[session_id_parameter, *schema.page_parameters],
        responses={200: schema.message_list_result, **schema.assistant_errors},
    )
    @action(detail=True, methods=["get"])
    def messages(self, request: Request, pk: UUID) -> ApiResponse:
        """助手会话消息"""
        session = services.owned_session(self.access.user_id, pk)
        return self._page(session.messages.select_related("feedback"), AssistantMessageSerializer)

    @extend_schema(
        parameters=[session_id_parameter, OpenApiParameter("message_id", UUID, OpenApiParameter.PATH)],
        request=FeedbackInputSerializer,
        responses={200: schema.feedback_result, **schema.assistant_errors},
    )
    @action(detail=True, methods=["put"], url_path=rf"messages/(?P<message_id>{UUIDConverter.regex})/feedback")
    def feedback(self, request: Request, pk: UUID, message_id: UUID) -> ApiResponse:
        """提交回答反馈"""
        serializer = FeedbackInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feedback = services.save_feedback(self.access.user_id, pk, message_id, **serializer.validated_data)
        return ApiResponse(data=AssistantFeedbackSerializer(feedback).data)


class AssistantInternalViewSet(EmployeeAssistantViewSet):
    """助手内网调用"""

    authentication_classes = (InternalServiceUserAuthentication, *api_settings.DEFAULT_AUTHENTICATION_CLASSES)

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        verify_internal_request(request)
        super().initial(request, *args, **kwargs)

    @extend_schema(
        description=(
            "仅供 FastAPI 从内网转发同一用户 Bearer token。返回历史和发布知识片段，历史排除本次问题。"
            "会话已转人工时返回 409，请新建对话。"
        ),
        request=QuestionInputSerializer,
        parameters=[session_id_parameter, *internal_headers],
        responses={201: schema.question_result, **schema.internal_errors, 409: schema.ticket_error_result},
    )
    @action(detail=True, methods=["post"])
    def question(self, request: Request, pk: UUID) -> ApiResponse:
        """记录用户提问"""
        serializer = QuestionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        check_rate(self.access.user_id, "assistant-context", 60)
        return ApiResponse(
            data=services.record_question(self.access.user_id, pk, **serializer.validated_data), status=201
        )

    @extend_schema(
        description="仅供 FastAPI 内网调用。转人工后仍可写回已有提问的回答，重放返回首次保存的回答 ID。",
        request=AnswerInputSerializer,
        parameters=[session_id_parameter, *internal_headers],
        responses={200: schema.answer_result, **schema.internal_errors},
    )
    @action(detail=True, methods=["post"])
    def answer(self, request: Request, pk: UUID) -> ApiResponse:
        """记录助手回答"""
        serializer = AnswerInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        check_rate(self.access.user_id, "assistant-answer", 60)
        answer_id = services.record_answer(self.access.user_id, pk, **serializer.validated_data)
        return ApiResponse(data={"assistant_message_id": answer_id})

    @extend_schema(
        description="仅供 FastAPI 内网读取本人会话的转人工草稿上下文。",
        parameters=[session_id_parameter, *internal_headers],
        responses={200: schema.context_result, **schema.internal_errors},
    )
    @action(detail=True, methods=["get"])
    def context(self, request: Request, pk: UUID) -> ApiResponse:
        """读取转人工上下文"""
        check_rate(self.access.user_id, "assistant-context", 60)
        session = services.owned_session(self.access.user_id, pk)
        return ApiResponse(data=services.conversation_context(session))


class AssistantFeedbackViewSet(AssistantViewSet):
    """AI 反馈"""

    serializer_class = AssistantFeedbackSerializer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not self.access.admin:
            raise PermissionDenied("仅管理员可查看 AI 反馈")

    def _dates(self, request: Request) -> dict[str, Any]:
        serializer = AssistantDateRangeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @extend_schema(
        parameters=[*schema.page_parameters, *schema.date_parameters],
        responses={200: schema.downvote_list_result, **schema.assistant_errors},
    )
    @action(detail=False, methods=["get"])
    def downvotes(self, request: Request) -> ApiResponse:
        """被点踩的回答"""
        queryset = AssistantFeedback.objects.filter(
            services.date_filter("updated_time", **self._dates(request)), vote=AssistantFeedback.Vote.DOWN
        ).select_related("message__session__user", "message__session__ticket", "message__user_message")
        return self._page(queryset, DownvoteSerializer)

    @extend_schema(
        parameters=[*schema.page_parameters, *schema.date_parameters],
        responses={200: schema.handoff_list_result, **schema.assistant_errors},
    )
    @action(detail=False, methods=["get"])
    def handoffs(self, request: Request) -> ApiResponse:
        """转人工会话列表"""
        queryset = (
            AssistantSession.all_objects.filter(
                services.date_filter("ticket__created_time", **self._dates(request)), ticket__isnull=False
            )
            .select_related("ticket", "user")
            .order_by("-ticket__created_time", "-pk")
        )
        return self._page(queryset, HandoffSessionSerializer)

    @extend_schema(parameters=schema.date_parameters, responses={200: schema.stats_result, **schema.assistant_errors})
    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> ApiResponse:
        """AI 问答统计"""
        return ApiResponse(data=services.assistant_stats(**self._dates(request)))
