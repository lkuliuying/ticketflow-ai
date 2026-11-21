from typing import Any, cast

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404
from django.utils.functional import cached_property
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request

from common.core.modelset.crud import DetailAction
from common.core.modelset.viewsets import OnlyListModelSet
from common.core.response import ApiResponse
from identity.models import UserInfo
from knowledge.api_schema import article_list_result, article_result, context_result
from knowledge.filters import ArticleFilter
from knowledge.models import ArticleStatus, KnowledgeArticle
from knowledge.serializers import (
    ArticleColumnsSerializer,
    ArticleCreateSerializer,
    ArticleListSerializer,
    ArticleSerializer,
    ArticleUpdateSerializer,
)
from knowledge.services import article_key, count_article_view, create_article, references_for
from tickets.cache import check_rate
from tickets.models import Category
from tickets.policy import TicketAccess, has_permission
from tickets.serializers import TicketSerializer
from tickets.views import TicketViewSet


@extend_schema_view(list=extend_schema(responses=article_list_result))
class ArticleViewSet(OnlyListModelSet, DetailAction):
    """工单知识库"""

    queryset = KnowledgeArticle.objects.all()
    serializer_class = ArticleSerializer
    list_serializer_class = ArticleListSerializer
    create_serializer_class = ArticleCreateSerializer
    search_columns_serializer_class = ArticleColumnsSerializer
    partial_update_serializer_class = ArticleUpdateSerializer
    filterset_class = ArticleFilter
    lookup_value_regex = TicketViewSet.lookup_value_regex
    table_fields = ArticleSerializer.Meta.table_fields

    @cached_property
    def actor(self) -> UserInfo:
        return cast(UserInfo, self.request.user)

    @cached_property
    def access(self) -> TicketAccess:
        return TicketAccess.for_user(self.actor)

    def get_queryset(self) -> QuerySet[KnowledgeArticle]:
        if not self.request.user.is_authenticated:
            return self.queryset.none()
        queryset = super().get_queryset()
        if not self.access.admin:
            queryset = queryset.filter(
                Q(status=ArticleStatus.PUBLISHED) | Q(status=ArticleStatus.DRAFT, creator=self.actor)
            )
        if self.action in ("retrieve", "list"):
            queryset = queryset.defer("body_markdown")
        if self.action == "partial_update":
            queryset = queryset.select_for_update(of=("self",))
        return queryset

    def data_permission_fallback_q(self, request: Request) -> Q:
        return Q()

    def get_object(self) -> KnowledgeArticle:
        try:
            return super().get_object()
        except Http404 as exc:
            raise NotFound("文章不存在") from exc

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context["ticket_access"] = self.access
        return context

    def _response(self, article: KnowledgeArticle, status: int = 200) -> ApiResponse:
        data = ArticleSerializer(article, context=self.get_serializer_context()).data
        can_update = has_permission(self.actor, "partialUpdate:TicketFlowKnowledge")
        data["viewer"] = {
            "can_edit": can_update
            and (self.access.admin or (article.status == ArticleStatus.DRAFT and article.creator_id == self.actor.pk)),
            "can_publish": can_update and self.access.admin,
        }
        return ApiResponse(data=data, status=status)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """知识库文章列表"""
        response = super().list(request, *args, **kwargs)
        response.data["data"]["can_create_standalone"] = self.access.admin and has_permission(
            self.actor, "create:TicketFlowKnowledge"
        )
        return response

    @extend_schema(responses=article_result)
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """知识库文章详情"""
        article = self.get_object()
        count_article_view(article)
        return self._response(article)

    @extend_schema(responses={201: article_result})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """创建知识库草稿"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        article = create_article(self.actor, self.access, values, values.pop("source_ticket_id", None))
        return self._response(article, status=201)

    @extend_schema(responses=article_result)
    @transaction.atomic
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> ApiResponse:
        """更新知识库文章"""
        article = self.get_object()
        serializer = self.get_serializer(article, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        status = serializer.validated_data.get("status", article.status)
        if not self.access.admin and (article.status != ArticleStatus.DRAFT or status != ArticleStatus.DRAFT):
            raise PermissionDenied("只有知识库管理员可发布、归档或编辑已发布文章")
        old_key = article_key(article)
        serializer.save(modifier=self.actor)
        transaction.on_commit(lambda: cache.delete(old_key), robust=True)
        return self._response(article)


class TicketAiContextView(TicketViewSet):
    """工单 AI 上下文"""

    @extend_schema(responses=context_result)
    def context(self, request: Request, **kwargs: Any) -> ApiResponse:
        """读取工单 AI 上下文"""
        ticket = self.get_object()
        if not self.access.can_handle(ticket):
            raise PermissionDenied("无权使用此工单的 AI 上下文")
        check_rate(self.actor.pk, "ai-context", 60)
        payload = TicketSerializer(ticket, context=self.get_serializer_context()).data
        fields = ("pk", "title", "description", "category", "priority", "version")
        if not all(field in payload for field in fields):
            raise PermissionDenied("当前字段权限无法提供工单 AI 上下文")
        return ApiResponse(
            data={
                "ticket": {"id" if field == "pk" else field: payload[field] for field in fields},
                "categories": list(Category.values),
                "references": references_for(ticket),
            }
        )
