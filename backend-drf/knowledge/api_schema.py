from rest_framework import serializers

from knowledge.serializers import ArticleListSerializer, ArticleSerializer
from tickets.api_schema import envelope, page


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


class AiContextSerializer(serializers.Serializer):
    ticket = TicketContextSerializer()
    categories = serializers.ListField(child=serializers.CharField())
    references = KnowledgeReferenceSerializer(many=True)


article_result = envelope("KnowledgeArticleResult", ArticleSerializer())
article_list_result = envelope("KnowledgeListResult", page("KnowledgeArticlePage", ArticleListSerializer(many=True)))
context_result = envelope("TicketAiContextResult", AiContextSerializer())
