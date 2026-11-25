from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Upper
from pgvector.django import VectorField

from common.core.models import DbAuditModel, DbUuidModel


class ArticleStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    PUBLISHED = "PUBLISHED", "已发布"
    ARCHIVED = "ARCHIVED", "已归档"


class KnowledgeArticle(DbAuditModel, DbUuidModel):
    title = models.CharField("标题", max_length=200)
    body_markdown = models.TextField("正文")
    category = models.CharField("分类", max_length=12)
    tags = models.JSONField("标签", default=list, blank=True)
    status = models.CharField("状态", max_length=10, choices=ArticleStatus.choices, default=ArticleStatus.DRAFT)
    view_count = models.PositiveBigIntegerField("浏览次数", default=0)
    source_ticket = models.OneToOneField(
        "tickets.Ticket", on_delete=models.SET_NULL, related_name="knowledge_article", null=True, blank=True
    )

    class Meta:
        verbose_name = "知识库文章"
        ordering = ("-updated_time", "-id")
        indexes = [
            models.Index(fields=["status", "category", "-updated_time"], name="tf_kb_status_category_idx"),
            GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="tf_kb_title_trgm_idx"),
            GinIndex(OpClass(Upper("body_markdown"), name="gin_trgm_ops"), name="tf_kb_body_trgm_idx"),
        ]

    def __str__(self) -> str:
        return self.title


class KnowledgeChunk(DbUuidModel):
    article = models.ForeignKey(KnowledgeArticle, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    embedding_vector = VectorField(blank=True, editable=False, null=True)
    embedding_model = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = "知识分块"
        ordering = ("article", "chunk_index")
        constraints = [models.UniqueConstraint(fields=["article", "chunk_index"], name="tf_kb_chunk_once")]
        indexes = [models.Index(fields=["article", "chunk_index"], name="tf_kb_chunk_order_idx")]

    def __str__(self) -> str:
        return f"{self.article_id}#{self.chunk_index}"
