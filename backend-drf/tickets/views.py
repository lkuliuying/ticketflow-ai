from typing import Any, cast
from uuid import UUID

from django.apps import apps
from django.core.cache import cache
from django.db.models import Count, Q, QuerySet
from django.http import Http404
from django.urls.converters import UUIDConverter
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
from tickets import services
from tickets.api_schema import (
    assignees_result,
    comment_result,
    dashboard_result,
    ticket_detail_result,
    ticket_list_result,
    ticket_result,
    timeline_result,
)
from tickets.cache import check_rate, dashboard_key
from tickets.filters import TicketFilter
from tickets.models import Status, Ticket
from tickets.policy import TicketAccess, assignment_candidates, has_permission
from tickets.serializers import (
    AssigneeSerializer,
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
    BaseViewSet, DetailAction, SearchColumnsAction, SearchFieldsAction, OnlyExportDataAction, GenericViewSet
):
    """工单"""

    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    create_serializer_class = TicketCreateSerializer
    search_columns_serializer_class = TicketColumnsSerializer
    transition_serializer_class = TransitionSerializer
    assign_serializer_class = AssignmentSerializer
    comments_serializer_class = CommentSerializer
    ai_metadata_serializer_class = SuggestionSerializer
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
        return self.access.scope(super().get_queryset())

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

    @extend_schema(
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        responses={200: ticket_result, 201: ticket_result},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """创建工单"""
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > 128:
            raise ValidationError({"Idempotency-Key": "请提供 1 至 128 字符的幂等键"})
        check_rate(self.actor.pk, "create", 30)
        values = cast(services.NewTicket, self._values(request))
        ticket, created = services.create_ticket(self.actor, key, values)
        return self._ticket_response(ticket, status=201 if created else 200)

    @extend_schema(responses=ticket_detail_result)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """工单详情"""
        ticket = self.get_object()
        data = self.get_serializer(ticket).data
        can_handle = self.access.can_handle(ticket)
        is_superuser = self.actor.is_superuser
        permission_codes = set() if is_superuser else get_user_permission_codes(self.actor)
        can_comment = is_superuser or "comments:TicketFlowTickets" in permission_codes
        data["viewer"] = {
            "can_handle": can_handle,
            "can_assign": can_handle
            and ticket.status != Status.CLOSED
            and (is_superuser or {"assign:TicketFlowTickets", "assignees:TicketFlowTickets"} <= permission_codes),
            "can_reply": can_comment and self.access.can_reply(ticket),
            "can_comment_internal": can_comment and can_handle,
            "can_archive": (
                can_handle
                and ticket.status == Status.CLOSED
                and apps.is_installed("knowledge")
                and (is_superuser or "create:TicketFlowKnowledge" in permission_codes)
                and not Ticket.objects.filter(pk=ticket.pk, knowledge_article__isnull=False).exists()
            ),
        }
        data["available_transitions"] = self.access.targets(ticket)
        data["timeline"] = first_page(ticket, self.access.can_handle(ticket))
        return ApiResponse(data=data)

    @extend_schema(parameters=[OpenApiParameter("q", str)], responses=assignees_result)
    @action(detail=True, methods=["get"], filterset_class=None)
    def assignees(self, request: Request, pk: UUID) -> ApiResponse:
        """工单指派候选人"""
        ticket = self.get_object()
        if not self.access.can_handle(ticket) or not has_permission(self.actor, "assign:TicketFlowTickets"):
            raise PermissionDenied("无权指派此工单")
        queryset = assignment_candidates(self.access)
        query = request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(Q(username__icontains=query) | Q(nickname__icontains=query))
        return ApiResponse(data=AssigneeSerializer(queryset[:20], many=True).data)

    @extend_schema(responses=timeline_result)
    @action(detail=True, methods=["get"])
    def timeline(self, request: Request, pk: UUID) -> ApiResponse:
        """工单时间线"""
        ticket = self.get_object()
        rows = timeline_rows(ticket, self.access.can_handle(ticket))
        page = self.paginate_queryset(rows)
        return ApiResponse(data=self.get_paginated_response(page).data)

    @extend_schema(responses=ticket_result)
    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: UUID) -> ApiResponse:
        """工单流转"""
        scope = self.filter_queryset(self.get_queryset())
        ticket = services.transition(scope, pk, self.actor, self.access, **self._values(request))
        return self._ticket_response(ticket)

    @extend_schema(responses=ticket_result)
    @action(detail=True, methods=["post"])
    def assign(self, request: Request, pk: UUID) -> ApiResponse:
        """指派工单"""
        scope = self.filter_queryset(self.get_queryset())
        ticket = services.assign(scope, pk, self.actor, self.access, **self._values(request))
        return self._ticket_response(ticket)

    @extend_schema(responses={201: comment_result})
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
        sql, params = queryset.query.sql_with_params()
        key = dashboard_key(self.actor.pk, sql, params)
        data = cache.get(key)
        if data is None:
            data = {
                "status": dict(queryset.values("status").annotate(total=Count("pk")).values_list("status", "total")),
                "priority": dict(
                    queryset.values("priority").annotate(total=Count("pk")).values_list("priority", "total")
                ),
                "sla": {
                    state: TicketFilter().filter_sla(queryset, "sla", state).count()
                    for state in ("DUE_SOON", "OVERDUE", "MET", "ON_TRACK")
                },
            }
            cache.set(key, data, 30)
        return ApiResponse(data=data)
