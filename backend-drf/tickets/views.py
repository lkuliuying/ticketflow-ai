from typing import Any, cast
from uuid import UUID

from django.apps import apps
from django.core.cache import cache
from django.db.models import Count, F, Q, QuerySet
from django.http import Http404
from django.urls.converters import UUIDConverter
from django.utils import timezone
from django.utils.functional import cached_property
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from common.core.modelset.base import BaseViewSet
from common.core.modelset.crud import DetailAction
from common.core.modelset.import_export import OnlyExportDataAction
from common.core.modelset.metadata import SearchColumnsAction, SearchFieldsAction
from common.core.permission import get_user_permission_codes
from common.core.response import ApiResponse
from identity.models import UserInfo
from tickets import chat_services, services
from tickets.api_schema import (
    assignees_result,
    comment_result,
    dashboard_result,
    rating_result,
    ticket_detail_result,
    ticket_error_result,
    ticket_list_result,
    ticket_result,
    timeline_result,
)
from tickets.assistant_schema import assistant_errors, page_parameters, ticket_session_result
from tickets.assistant_serializers import AssistantSessionSerializer, AssistantTranscriptMessageSerializer
from tickets.cache import check_rate, dashboard_key
from tickets.chat_views import TicketMediaChatMixin
from tickets.filters import TicketFilter
from tickets.models import Status, Ticket
from tickets.policy import TicketAccess, assignment_candidates, has_permission
from tickets.rating_serializers import RatingInputSerializer, TicketRatingSerializer
from tickets.serializers import (
    AssigneeSerializer,
    AssignmentReturnSerializer,
    AssignmentSerializer,
    CommentSerializer,
    SuggestionSerializer,
    TicketColumnsSerializer,
    TicketCreateSerializer,
    TicketSerializer,
    TransitionSerializer,
)
from tickets.timeline import first_page, timeline_rows


@extend_schema_view(list=extend_schema(responses=ticket_list_result))
class TicketViewSet(
    TicketMediaChatMixin,
    BaseViewSet,
    DetailAction,
    SearchColumnsAction,
    SearchFieldsAction,
    OnlyExportDataAction,
    GenericViewSet,
):
    """工单"""

    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    create_serializer_class = TicketCreateSerializer
    search_columns_serializer_class = TicketColumnsSerializer
    transition_serializer_class = TransitionSerializer
    assign_serializer_class = AssignmentSerializer
    return_ticket_serializer_class = AssignmentReturnSerializer
    comments_serializer_class = CommentSerializer
    ai_metadata_serializer_class = SuggestionSerializer
    rating_serializer_class = RatingInputSerializer
    filterset_class = TicketFilter
    lookup_value_regex = UUIDConverter.regex
    select_related_fields = ("submitter", "assignee", "department")
    table_fields = TicketSerializer.Meta.table_fields

    @cached_property
    def actor(self) -> UserInfo:
        return cast(UserInfo, self.request.user)

    @cached_property
    def access(self) -> TicketAccess:
        return TicketAccess.for_user(self.actor)

    def get_queryset(self) -> QuerySet[Ticket]:
        if not self.request.user.is_authenticated:
            return self.queryset.none()
        queryset = self.access.scope(super().get_queryset())
        if self.action == "retrieve":
            return queryset.select_related("rating__rater", "rating__handler", "assistant_session").prefetch_related(
                "attachments__file"
            )
        return queryset

    def data_permission_fallback_q(self, request: Request) -> Q:
        # 已在 get_queryset 应用业务范围，底座有显式数据权限时继续求交。
        return Q()

    def get_object(self) -> Ticket:
        try:
            return super().get_object()
        except Http404 as exc:
            raise NotFound("工单不存在") from exc

    def _ticket_response(self, ticket: Ticket, status: int = 200) -> ApiResponse:
        data = TicketSerializer(ticket, context=self.get_serializer_context()).data
        return ApiResponse(data=data, status=status)

    def _values(self, request: Request) -> dict[str, Any]:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def list(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """工单列表"""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = list(page) if page is not None else list(queryset)
        counts = chat_services.unread_counts([item.pk for item in items], self.actor.pk)
        context = {**self.get_serializer_context(), "unread_chat_counts": counts}
        serializer = self.get_serializer(items, many=True, context=context)
        if page is not None:
            return ApiResponse(data=self.get_paginated_response(serializer.data).data)
        return ApiResponse(data=serializer.data)

    @extend_schema(
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        responses={200: ticket_result, 201: ticket_result, **assistant_errors, 409: ticket_error_result},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """创建工单"""
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > 128:
            raise ValidationError({"Idempotency-Key": "请提供 1 至 128 字符的幂等键"})
        check_rate(self.actor.pk, "create", 30)
        values = dict(self._values(request))
        session_id = values.pop("assistant_session_id", None)
        attachment_ids = values.pop("attachment_ids", None)
        if session_id is None and request.data.get("assistant_session_id") is not None:
            raise PermissionDenied("无权关联助手会话")
        ticket, created = services.create_ticket(
            self.actor,
            key,
            cast(services.NewTicket, values),
            assistant_session_id=session_id,
            attachment_ids=attachment_ids,
        )
        return self._ticket_response(ticket, status=201 if created else 200)

    @extend_schema(responses=ticket_detail_result)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """工单详情"""
        ticket = self.get_object()
        data = self.get_serializer(ticket).data
        can_handle = self.access.can_handle(ticket)
        read_only = self.access.read_only(ticket)
        is_superuser = self.actor.is_superuser
        permission_codes = set() if is_superuser else get_user_permission_codes(self.actor)
        can_comment = is_superuser or "comments:TicketFlowTickets" in permission_codes
        can_send = is_superuser or chat_services.CHAT_SEND_PERMISSION in permission_codes
        rating = getattr(ticket, "rating", None)
        data["viewer"] = {
            "can_handle": can_handle,
            "can_assign": self.access.admin
            and ticket.status != Status.CLOSED
            and (is_superuser or {"assign:TicketFlowTickets", "assignees:TicketFlowTickets"} <= permission_codes),
            "can_reply": can_send and self.access.can_reply(ticket),
            "can_comment_internal": can_comment and can_handle,
            "can_return": self.access.can_return(ticket) and "returnTicket:TicketFlowTickets" in permission_codes,
            "can_rate": (
                ticket.submitter_id == self.actor.pk
                and ticket.status == Status.CLOSED
                and rating is None
                and (is_superuser or "rating:TicketFlowTickets" in permission_codes)
            ),
            "read_only": read_only,
            "can_archive": (
                ticket.status == Status.CLOSED
                and self.access.can_archive(ticket, read_only=read_only)
                and apps.is_installed("knowledge")
                and (is_superuser or "create:TicketFlowKnowledge" in permission_codes)
                and not Ticket.objects.filter(pk=ticket.pk, knowledge_article__isnull=False).exists()
            ),
        }
        data["available_transitions"] = self.access.targets(ticket)
        data["timeline"] = first_page(ticket, can_handle or read_only)
        data["rating"] = (
            TicketRatingSerializer(rating, ignore_field_permission=True).data
            if rating is not None and (self.access.admin or self.actor.pk in (rating.rater_id, rating.handler_id))
            else None
        )
        session = getattr(ticket, "assistant_session", None)
        can_read_session = self.access.can_read_assistant_session(ticket) and (
            is_superuser or "assistantSession:TicketFlowTickets" in permission_codes
        )
        data["assistant_session_id"] = str(session.pk) if session is not None and can_read_session else None
        data["attachments"] = [
            {
                "id": str(att.pk),
                "filename": att.file.filename,
                "filesize": att.file.filesize,
                "mime_type": att.file.mime_type or "",
                "thumb_url": f"/api/tickets/{ticket.pk}/attachments/{att.pk}?size=thumb",
                "url": f"/api/tickets/{ticket.pk}/attachments/{att.pk}",
            }
            for att in ticket.attachments.all()
        ]
        data["chat_state"] = chat_services.chat_state(ticket, self.access, can_send=can_send)
        return ApiResponse(data=data)

    @extend_schema(parameters=page_parameters, responses={200: ticket_session_result, **assistant_errors})
    @action(detail=True, methods=["get"], url_path="assistant-session", filterset_class=None)
    def assistant_session(self, request: Request, pk: UUID) -> ApiResponse:
        """工单关联会话"""
        ticket = self.get_object()
        if not self.access.can_read_assistant_session(ticket):
            raise PermissionDenied("无权查看关联会话")
        session = getattr(ticket, "assistant_session", None)
        if session is None:
            raise NotFound("工单没有关联会话")
        rows = self.paginate_queryset(session.messages.all())
        messages = self.get_paginated_response(AssistantTranscriptMessageSerializer(rows, many=True).data).data
        return ApiResponse(data={"session": AssistantSessionSerializer(session).data, "messages": messages})

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str),
            OpenApiParameter("department_id", UUID, description="技能组 UUID。省略或留空时忽略筛选，非法值返回 400。"),
        ],
        responses={200: assignees_result, 400: ticket_error_result},
    )
    @action(detail=True, methods=["get"], filterset_class=None)
    def assignees(self, request: Request, pk: UUID) -> ApiResponse:
        """工单指派候选人"""
        self.get_object()
        if not self.access.admin or not has_permission(self.actor, "assign:TicketFlowTickets"):
            raise PermissionDenied("无权指派此工单")
        queryset = assignment_candidates()
        department = request.query_params.get("department_id", "").strip()
        if department:
            try:
                department_id = UUID(department)
            except ValueError as exc:
                raise ValidationError({"department_id": "请输入有效的技能组 UUID"}) from exc
            queryset = queryset.filter(dept_id=department_id)
        query = request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(Q(username__icontains=query) | Q(nickname__icontains=query))
        return ApiResponse(data=AssigneeSerializer(queryset[:20], many=True).data)

    @extend_schema(responses=timeline_result)
    @action(detail=True, methods=["get"])
    def timeline(self, request: Request, pk: UUID) -> ApiResponse:
        """工单时间线"""
        ticket = self.get_object()
        rows = timeline_rows(ticket, self.access.can_handle(ticket) or self.access.read_only(ticket))
        page = self.paginate_queryset(rows)
        return ApiResponse(data=self.get_paginated_response(page).data)

    @extend_schema(responses=ticket_result)
    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: UUID) -> ApiResponse:
        """工单流转"""
        scope = self.filter_queryset(self.get_queryset())
        ticket = services.transition(scope, pk, self.actor, self.access, **self._values(request))
        return self._ticket_response(ticket)

    @extend_schema(
        responses={
            201: rating_result,
            400: ticket_error_result,
            403: ticket_error_result,
            404: ticket_error_result,
            409: ticket_error_result,
        },
    )
    @action(detail=True, methods=["post"], filterset_class=None)
    def rating(self, request: Request, pk: UUID) -> ApiResponse:
        """提交工单评价"""
        scope = self.filter_queryset(self.get_queryset())
        values = cast(services.RatingInput, self._values(request))
        rating = services.create_rating(scope, pk, self.actor, **values)
        data = TicketRatingSerializer(rating, context=self.get_serializer_context()).data
        return ApiResponse(data=data, status=201)

    @extend_schema(responses=ticket_result)
    @action(detail=True, methods=["post"])
    def assign(self, request: Request, pk: UUID) -> ApiResponse:
        """指派工单"""
        scope = self.filter_queryset(self.get_queryset())
        ticket = services.assign(scope, pk, self.actor, self.access, **self._values(request))
        return self._ticket_response(ticket)

    @extend_schema(responses={200: ticket_result, 403: None, 409: None})
    @action(detail=True, methods=["post"], url_path="return")
    def return_ticket(self, request: Request, pk: UUID) -> ApiResponse:
        """退回工单"""
        scope = self.filter_queryset(self.get_queryset())
        ticket = services.return_ticket(scope, pk, self.actor, self.access, **self._values(request))
        return self._ticket_response(ticket)

    @extend_schema(responses={201: comment_result, 400: ticket_error_result})
    @action(detail=True, methods=["post"])
    def comments(self, request: Request, pk: UUID) -> ApiResponse:
        """工单回复"""
        check_rate(self.actor.pk, "comment", 60)
        scope = self.filter_queryset(self.get_queryset())
        comment = services.add_comment(scope, pk, self.actor, self.access, **self._values(request))
        data = CommentSerializer(comment).data
        data.update({"id": comment.pk, "created_time": comment.created_time, "author_id": comment.author_id})
        return ApiResponse(data=data, status=201)

    @extend_schema(responses=ticket_result)
    @action(detail=True, methods=["post"], url_path="ai-metadata")
    def ai_metadata(self, request: Request, pk: UUID) -> ApiResponse:
        """采纳工单建议"""
        scope = self.filter_queryset(self.get_queryset())
        ticket = services.save_ai_metadata(scope, pk, self.actor, self.access, **self._values(request))
        return self._ticket_response(ticket)

    @extend_schema(responses=dashboard_result)
    @action(detail=False, methods=["get"])
    def dashboard(self, request: Request) -> ApiResponse:
        """工单看板"""
        queryset = self.filter_queryset(self.get_queryset()).order_by()
        sql, params = ("", ()) if queryset.query.is_empty() else queryset.query.sql_with_params()
        assignments = ("unassigned",) if self.access.admin else ("current", "history") if self.access.agent else ()
        key = dashboard_key(self.actor.pk, sql, (*params, assignments), is_admin=self.access.admin)
        data = cache.get(key)
        if data is None:
            now = timezone.now()
            active = Q(resolved_at__isnull=True)
            aggregates: dict[str, Any] = {
                "sla_DUE_SOON": Count(
                    "pk", filter=active & Q(sla_due_at__gt=now, sla_due_at__lte=now + services.SLA_WARNING)
                ),
                "sla_OVERDUE": Count(
                    "pk", filter=(active & Q(sla_due_at__lte=now)) | Q(resolved_at__gt=F("sla_due_at"))
                ),
                "sla_MET": Count("pk", filter=Q(resolved_at__lte=F("sla_due_at"))),
                "sla_ON_TRACK": Count("pk", filter=active & Q(sla_due_at__gt=now + services.SLA_WARNING)),
            }
            if "unassigned" in assignments:
                aggregates["assign_unassigned"] = Count(
                    "pk", filter=Q(assignee__isnull=True) & ~Q(status=Status.CLOSED)
                )
            if "current" in assignments:
                aggregates["assign_current"] = Count("pk", filter=Q(assignee_id=self.actor.pk))
            if "history" in assignments:
                aggregates["assign_history"] = Count(
                    "pk", filter=Q(self.access.history()) & ~Q(assignee_id=self.actor.pk)
                )
            totals = queryset.aggregate(**aggregates)
            data = {
                "status": dict(queryset.values("status").annotate(total=Count("pk")).values_list("status", "total")),
                "priority": dict(
                    queryset.values("priority").annotate(total=Count("pk")).values_list("priority", "total")
                ),
                "sla": {state: totals[f"sla_{state}"] for state in ("DUE_SOON", "OVERDUE", "MET", "ON_TRACK")},
                "assignment": {assignment: totals[f"assign_{assignment}"] for assignment in assignments},
            }
            cache.set(key, data, 15)
        return ApiResponse(data=data)
