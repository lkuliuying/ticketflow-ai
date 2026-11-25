from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from knowledge.serializers import ArticleListSerializer, ArticleSerializer
from tickets.api_schema import envelope


class ArticleViewerSerializer(serializers.Serializer):
    can_edit = serializers.BooleanField(help_text="持有更新权限的工单管理员、知识维护人员或草稿作者可编辑。")
    can_publish = serializers.BooleanField(help_text="持有更新权限的工单管理员或知识维护人员可发布或归档。")


@extend_schema_serializer(component_name="Article")
class ArticleResultSerializer(ArticleSerializer):
    viewer = ArticleViewerSerializer(read_only=True)

    class Meta(ArticleSerializer.Meta):
        fields = (*ArticleSerializer.Meta.fields, "viewer")


class KnowledgeArticlePageSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    results = ArticleListSerializer(many=True)
    can_create_standalone = serializers.BooleanField()


class KnowledgeReferenceSerializer(serializers.Serializer):
    article_id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    excerpt = serializers.CharField(max_length=800)


class TicketContextSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField()
    category = serializers.CharField()
    priority = serializers.CharField()
    version = serializers.IntegerField()


class TicketChatTurnSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=("submitter", "handler", "system"))
    sender = serializers.CharField()
    content = serializers.CharField()
    created_time = serializers.DateTimeField()


class AiContextSerializer(serializers.Serializer):
    ticket = TicketContextSerializer()
    categories = serializers.ListField(child=serializers.CharField())
    references = KnowledgeReferenceSerializer(many=True)
    recent_messages = TicketChatTurnSerializer(many=True)


article_result = envelope("KnowledgeArticleResult", ArticleResultSerializer())
article_list_result = envelope("KnowledgeListResult", KnowledgeArticlePageSerializer())
context_result = envelope("TicketAiContextResult", AiContextSerializer())
