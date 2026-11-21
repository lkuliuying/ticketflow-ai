from rest_framework import serializers

from common.core.serializers import BaseModelSerializer
from knowledge.models import ArticleStatus, KnowledgeArticle
from tickets.models import Category


class ArticleSerializer(BaseModelSerializer):
    serializer_choice_field = serializers.ChoiceField
    pk = serializers.UUIDField(read_only=True)
    source_ticket_id = serializers.SerializerMethodField()
    created_time = serializers.DateTimeField(format="iso-8601", read_only=True)
    updated_time = serializers.DateTimeField(format="iso-8601", read_only=True)

    class Meta:
        model = KnowledgeArticle
        fields: tuple[str, ...] = (
            "pk",
            "title",
            "body_markdown",
            "category",
            "tags",
            "status",
            "view_count",
            "source_ticket_id",
            "created_time",
            "updated_time",
        )
        read_only_fields: tuple[str, ...] = fields
        table_fields = ("title", "category", "tags", "status", "view_count", "updated_time")
        extra_kwargs = {"view_count": {"help_text": "仅访问已发布文章的详情时累计。"}}

    def get_source_ticket_id(self, article: KnowledgeArticle) -> str | None:
        access = self.context.get("ticket_access")
        if access and article.source_ticket_id and (access.admin or article.creator_id == access.user_id):
            return str(article.source_ticket_id)
        return None


class ArticleListSerializer(ArticleSerializer):
    class Meta(ArticleSerializer.Meta):
        fields = tuple(
            field for field in ArticleSerializer.Meta.fields if field not in ("body_markdown", "source_ticket_id")
        )
        read_only_fields = fields


class ArticleWriteSerializer(BaseModelSerializer):
    title = serializers.CharField(max_length=200)
    body_markdown = serializers.CharField(max_length=100000)
    category = serializers.ChoiceField(choices=Category.choices)
    tags = serializers.ListField(child=serializers.CharField(max_length=64), max_length=12, required=False)

    class Meta:
        model = KnowledgeArticle
        fields: tuple[str, ...] = ("title", "body_markdown", "category", "tags")


class ArticleCreateSerializer(ArticleWriteSerializer):
    source_ticket_id = serializers.UUIDField(required=False, allow_null=True)

    class Meta(ArticleWriteSerializer.Meta):
        fields = (*ArticleWriteSerializer.Meta.fields, "source_ticket_id")


class ArticleUpdateSerializer(ArticleWriteSerializer):
    status = serializers.ChoiceField(choices=ArticleStatus.choices, required=False)

    class Meta(ArticleWriteSerializer.Meta):
        fields = (*ArticleWriteSerializer.Meta.fields, "status")


class ArticleColumnsSerializer(ArticleSerializer):
    class Meta(ArticleSerializer.Meta):
        read_only_fields = tuple(
            name for name in ArticleSerializer.Meta.fields if name not in ArticleWriteSerializer.Meta.fields
        )
