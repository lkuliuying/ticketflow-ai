import django_filters as filters
from django.db.models import Q, QuerySet

from knowledge.models import ArticleStatus, KnowledgeArticle
from tickets.models import Category


class ArticleFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=ArticleStatus.choices)
    category = filters.ChoiceFilter(choices=Category.choices)
    q = filters.CharFilter(method="filter_q", max_length=200)
    tag = filters.CharFilter(method="filter_tag", max_length=64)

    class Meta:
        model = KnowledgeArticle
        fields = ("status", "category", "q", "tag")

    def filter_q(self, queryset: QuerySet[KnowledgeArticle], name: str, value: str) -> QuerySet[KnowledgeArticle]:
        return queryset.filter(Q(title__icontains=value) | Q(body_markdown__icontains=value))

    def filter_tag(self, queryset: QuerySet[KnowledgeArticle], name: str, value: str) -> QuerySet[KnowledgeArticle]:
        return queryset.filter(tags__contains=[value])
