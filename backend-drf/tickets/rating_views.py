import re
from collections import Counter
from typing import Any

import django_filters as filters
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q, QuerySet, Sum
from django.utils.functional import cached_property
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_field, extend_schema_view
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from common.core.modelset.base import BaseViewSet
from common.core.modelset.crud import ListAction
from common.core.modelset.metadata import SearchColumnsAction, SearchFieldsAction
from common.core.response import ApiResponse
from tickets.api_schema import rating_list_result, rating_summary_result, ticket_error_result
from tickets.models import RatingTag, TicketRating
from tickets.policy import TicketAccess
from tickets.rating_serializers import RatingSummarySerializer, TicketRatingSerializer

SCORES = [(str(score), str(score)) for score in range(1, 6)]
HANDLER_ID_LABEL = "处理人 ID"


class RatingDateBound(filters.IsoDateTimeFilter):
    input_type = "datetime"


class RatingHandlerIdField(forms.IntegerField):
    def to_python(self, value: Any) -> int | None:
        if value not in self.empty_values and not re.fullmatch(r"[+-]?[0-9]+", str(value).strip()):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return super().to_python(value)


@extend_schema_field({"type": "integer", "description": HANDLER_ID_LABEL})
class RatingHandlerIdFilter(filters.Filter):
    field_class = RatingHandlerIdField


class RatingDateFilter(filters.FilterSet):
    created_from = RatingDateBound(field_name="created_time", lookup_expr="gte", label="评价开始时间")
    created_to = RatingDateBound(field_name="created_time", lookup_expr="lte", label="评价结束时间")

    class Meta:
        model = TicketRating
        fields: tuple[str, ...] = ("created_from", "created_to")


class RatingFilter(RatingDateFilter):
    handler_id = RatingHandlerIdFilter(label=HANDLER_ID_LABEL)
    satisfaction = filters.TypedChoiceFilter(choices=SCORES, coerce=int, label="满意度")
    handler_score = filters.TypedChoiceFilter(choices=SCORES, coerce=int, label="处理人评分")
    resolved = filters.TypedChoiceFilter(
        choices=(("true", "已解决"), ("false", "未解决")), coerce=lambda value: value == "true", label="是否解决"
    )

    class Meta(RatingDateFilter.Meta):
        fields = ("handler_id", "satisfaction", "handler_score", "resolved", *RatingDateFilter.Meta.fields)


def _rating_counts() -> dict[str, Any]:
    return {
        "count": Count("pk"),
        "satisfaction_total": Sum("satisfaction", default=0),
        "handler_score_total": Sum("handler_score", default=0),
        "resolved_total": Count("pk", filter=Q(resolved=True)),
        **{tag: Count("pk", filter=Q(tags__contains=[tag])) for tag in RatingTag.values},
    }


def _metrics(counts: dict[str, int]) -> dict[str, Any]:
    count = counts.get("count", 0)
    return {
        "count": count,
        "avg_satisfaction": round(counts["satisfaction_total"] / count, 2) if count else None,
        "avg_handler_score": round(counts["handler_score_total"] / count, 2) if count else None,
        "resolved_rate": round(counts["resolved_total"] / count, 4) if count else None,
        "tags": {tag: counts[tag] for tag in RatingTag.values if counts.get(tag)},
    }


@extend_schema_view(list=extend_schema(responses=rating_list_result))
class TicketRatingViewSet(BaseViewSet, ListAction, SearchColumnsAction, SearchFieldsAction, GenericViewSet):
    """工单评价"""

    queryset = TicketRating.objects.all()
    serializer_class = TicketRatingSerializer
    filterset_class = RatingFilter
    table_fields = TicketRatingSerializer.Meta.table_fields

    @cached_property
    def access(self) -> TicketAccess:
        return TicketAccess.for_user(self.request.user)

    def get_queryset(self) -> QuerySet[TicketRating]:
        if not self.request.user.is_authenticated:
            return self.queryset.none()
        queryset = super().get_queryset()
        if self.action == "list":
            queryset = queryset.select_related("ticket", "rater", "handler")
        if self.access.admin:
            return queryset
        if self.access.agent:
            return queryset.filter(handler_id=self.access.user_id)
        return queryset.filter(rater_id=self.access.user_id)

    def data_permission_fallback_q(self, request: Request) -> Q:
        return Q()

    @extend_schema(
        parameters=[
            OpenApiParameter("created_from", OpenApiTypes.DATETIME, description="评价时间下界（含）。"),
            OpenApiParameter("created_to", OpenApiTypes.DATETIME, description="评价时间上界（含）。"),
        ],
        responses={200: rating_summary_result, 400: ticket_error_result, 403: ticket_error_result},
    )
    @action(detail=False, methods=["get"], filterset_class=RatingDateFilter)
    def summary(self, request: Request) -> ApiResponse:
        """工单评价汇总"""
        if not (self.access.admin or self.access.agent):
            raise PermissionDenied("无权查看工单评价汇总")
        queryset = self.filter_queryset(self.get_queryset()).order_by()
        if not self.access.admin:
            metrics = _metrics(queryset.aggregate(**_rating_counts()))
        else:
            groups = (
                queryset.values("handler_id", "handler__username")
                .annotate(**_rating_counts())
                .order_by(F("handler_id").asc(nulls_last=True))
            )
            counts: Counter[str] = Counter()
            by_handler = []
            for group in groups:
                handler_id = group.pop("handler_id")
                handler_name = group.pop("handler__username")
                counts.update(group)
                by_handler.append({"handler_id": handler_id, "handler_name": handler_name, **_metrics(group)})
            metrics = {**_metrics(counts), "by_handler": by_handler}
        return ApiResponse(data=RatingSummarySerializer(metrics).data)
