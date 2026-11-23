from typing import Any

import django_filters as filters
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import Http404
from django.urls.converters import UUIDConverter
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from common.core.modelset.base import BaseViewSet
from common.core.modelset.crud import DetailAction, ListAction
from common.core.modelset.metadata import SearchColumnsAction, SearchFieldsAction
from common.core.response import ApiResponse
from identity.models import DeptInfo, UserInfo
from tickets.accounts import (
    ROLE_CHOICES,
    ROLE_CODES,
    business_accounts,
    lock_account,
    reset_account_password,
    save_account,
)
from tickets.api_schema import envelope, page, ticket_error_result
from tickets.management_serializers import (
    AccountCreateSerializer,
    AccountPasswordSerializer,
    AccountSerializer,
    CategoryRouteInputSerializer,
    CategoryRouteSerializer,
    SkillGroupSerializer,
)
from tickets.models import Category, CategoryRoute
from tickets.policy import TicketAccess
from tickets.skill_groups import create_skill_group, default_group, set_category_route, skill_groups, update_skill_group

account_result = envelope("TicketFlowAccountResult", AccountSerializer())
account_list_result = envelope(
    "TicketFlowAccountListResult", page("TicketFlowAccountPage", AccountSerializer(many=True))
)
group_result = envelope("TicketFlowSkillGroupResult", SkillGroupSerializer())
group_list_result = envelope(
    "TicketFlowSkillGroupListResult", page("TicketFlowSkillGroupPage", SkillGroupSerializer(many=True))
)
route_result = envelope("TicketFlowCategoryRouteResult", CategoryRouteSerializer())
route_list_result = envelope("TicketFlowCategoryRouteListResult", CategoryRouteSerializer(many=True))

ACTIVE_CHOICES = (("true", "启用"), ("false", "停用"))


class ManagementFilter(filters.FilterSet):
    is_active = filters.TypedChoiceFilter(choices=ACTIVE_CHOICES, coerce=lambda value: value == "true", label="状态")


class AccountFilter(ManagementFilter):
    q = filters.CharFilter(method="search", label="用户名、姓名、手机或邮箱")
    role = filters.ChoiceFilter(choices=ROLE_CHOICES, method="filter_role", label="角色")
    skill_group = filters.ModelChoiceFilter(
        queryset=lambda request: skill_groups(), method="filter_skill_group", label="技能组"
    )

    class Meta:
        model = UserInfo
        fields = ("q", "role", "skill_group", "is_active")

    def search(self, queryset: QuerySet[UserInfo], name: str, value: str) -> QuerySet[UserInfo]:
        return queryset.filter(
            Q(username__icontains=value)
            | Q(nickname__icontains=value)
            | Q(phone__icontains=value)
            | Q(email__icontains=value)
        )

    def filter_role(self, queryset: QuerySet[UserInfo], name: str, value: str) -> QuerySet[UserInfo]:
        return queryset.filter(roles__code=ROLE_CODES[value])

    def filter_skill_group(self, queryset: QuerySet[UserInfo], name: str, group: DeptInfo) -> QuerySet[UserInfo]:
        return queryset.filter(dept=group, roles__code=ROLE_CODES["agent"])


class SkillGroupFilter(ManagementFilter):
    q = filters.CharFilter(field_name="name", lookup_expr="icontains", label="技能组名称")

    class Meta:
        model = DeptInfo
        fields = ("q", "is_active")


class BusinessManagementViewSet(
    BaseViewSet, ListAction, DetailAction, SearchColumnsAction, SearchFieldsAction, GenericViewSet
):
    permission_models: tuple = ()
    ordering = ["pk"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        user = request.user
        if not user.is_authenticated or user.is_superuser or not TicketAccess.for_user(user).admin:
            raise PermissionDenied("仅工单业务管理员可管理账号和技能组")

    def data_permission_fallback_q(self, request: Request) -> Q:
        return Q()

    def get_object(self) -> Any:
        try:
            return super().get_object()
        except Http404 as exc:
            raise NotFound("记录不存在") from exc


@extend_schema_view(
    list=extend_schema(responses=account_list_result),
    retrieve=extend_schema(responses={200: account_result, 404: ticket_error_result}),
)
class AccountViewSet(BusinessManagementViewSet):
    """账号管理"""

    lookup_value_regex = r"\d+"
    queryset = UserInfo.objects.all()
    serializer_class = AccountSerializer
    create_serializer_class = AccountCreateSerializer
    search_columns_serializer_class = AccountCreateSerializer
    filterset_class = AccountFilter
    table_fields = AccountSerializer.Meta.table_fields
    ordering_fields = ("pk", "username", "nickname", "phone", "email", "dept", "is_active")
    ordering = ["username", "pk"]
    select_related_fields = ("dept",)
    prefetch_related_fields = ("roles",)

    def get_queryset(self) -> QuerySet[UserInfo]:
        return business_accounts()

    @extend_schema(request=AccountCreateSerializer, responses={201: account_result, 400: ticket_error_result})
    @transaction.atomic
    def create(self, request: Request) -> ApiResponse:
        """创建业务账号"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = save_account(UserInfo(), request.user, serializer.validated_data.copy())
        return ApiResponse(data=self.get_serializer(account).data, status=201)

    @extend_schema(
        request=AccountSerializer,
        responses={200: account_result, 400: ticket_error_result, 403: ticket_error_result, 404: ticket_error_result},
    )
    @transaction.atomic
    def partial_update(self, request: Request, pk: int) -> ApiResponse:
        """编辑业务账号"""
        account = lock_account(pk)
        serializer = self.get_serializer(account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        save_account(account, request.user, serializer.validated_data.copy())
        return ApiResponse(data=self.get_serializer(account).data)

    @extend_schema(
        request=AccountPasswordSerializer,
        responses={200: envelope("TicketFlowResetPasswordResult"), 400: ticket_error_result, 404: ticket_error_result},
    )
    @action(detail=True, methods=["post"], url_path="reset-password", serializer_class=AccountPasswordSerializer)
    @transaction.atomic
    def reset_password(self, request: Request, pk: int) -> ApiResponse:
        """重置业务账号密码"""
        account = lock_account(pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reset_account_password(account, request.user, serializer.validated_data["password"])
        return ApiResponse()


def _route_data(category: str, group: DeptInfo | None) -> dict[str, Any]:
    return {
        "category": category,
        "label": Category(category).label,
        "skill_group": group.pk if group else None,
        "skill_group_name": group.name if group else None,
    }


@extend_schema_view(
    list=extend_schema(responses=group_list_result),
    retrieve=extend_schema(responses={200: group_result, 404: ticket_error_result}),
)
class SkillGroupViewSet(BusinessManagementViewSet):
    """技能组"""

    lookup_value_regex = UUIDConverter.regex
    queryset = DeptInfo.objects.all()
    serializer_class = SkillGroupSerializer
    filterset_class = SkillGroupFilter
    table_fields = SkillGroupSerializer.Meta.table_fields
    ordering = ["name", "pk"]

    def get_queryset(self) -> QuerySet[DeptInfo]:
        return skill_groups().annotate(is_default=default_group())

    @extend_schema(request=SkillGroupSerializer, responses={201: group_result, 400: ticket_error_result})
    def create(self, request: Request) -> ApiResponse:
        """创建技能组"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = create_skill_group(request.user, serializer.validated_data)
        return ApiResponse(data=self.get_serializer(self.get_queryset().get(pk=group.pk)).data, status=201)

    @extend_schema(
        request=SkillGroupSerializer,
        responses={200: group_result, 400: ticket_error_result, 404: ticket_error_result, 409: ticket_error_result},
    )
    @transaction.atomic
    def partial_update(self, request: Request, pk: str) -> ApiResponse:
        """编辑技能组"""
        group = self.get_queryset().select_for_update(no_key=True).filter(pk=pk).first()
        if group is None:
            raise NotFound("技能组不存在")
        serializer = self.get_serializer(group, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        update_skill_group(group, request.user, serializer.validated_data)
        return ApiResponse(data=self.get_serializer(group).data)

    @extend_schema(responses=route_list_result, filters=False)
    @action(detail=False, url_path="category-routes", serializer_class=CategoryRouteSerializer)
    def category_routes(self, request: Request) -> ApiResponse:
        """分类路由列表"""
        routes = {route.category: route.skill_group for route in CategoryRoute.objects.select_related("skill_group")}
        data = [_route_data(category, routes.get(category)) for category in Category.values]
        return ApiResponse(data=self.get_serializer(data, many=True).data)

    @extend_schema(
        responses={200: route_result, 400: ticket_error_result},
        request=CategoryRouteInputSerializer,
        parameters=[OpenApiParameter("category", str, OpenApiParameter.PATH, enum=Category.values)],
    )
    @action(
        detail=False,
        methods=["patch"],
        url_path=r"category-routes/(?P<category>[^/.]+)",
        url_name="category-route",
        serializer_class=CategoryRouteInputSerializer,
    )
    @transaction.atomic
    def category_route(self, request: Request, category: str) -> ApiResponse:
        """编辑分类路由"""
        if category not in Category.values:
            raise ValidationError({"category": "工单分类无效"})
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_category_route(category, serializer.validated_data["skill_group"])
        route = CategoryRoute.objects.select_related("skill_group").filter(category=category).first()
        return ApiResponse(
            data=CategoryRouteSerializer(_route_data(category, route.skill_group if route else None)).data
        )
