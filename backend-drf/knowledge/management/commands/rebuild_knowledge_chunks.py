from typing import Any

from django.core.management.base import BaseCommand

from knowledge.embeddings import sync_article_chunks
from knowledge.models import KnowledgeArticle


class Command(BaseCommand):
    help = "重建 TicketFlow 存量知识库文章的分块及已发布文章的向量"

    def handle(self, *args: Any, **options: Any) -> None:
        article_ids = KnowledgeArticle.objects.order_by("pk").values_list("pk", flat=True)
        articles = chunks = 0
        for article_id in article_ids.iterator(chunk_size=200):
            chunks += sync_article_chunks(article_id)
            articles += 1
        self.stdout.write(f"处理文章 {articles} 篇，写入分块 {chunks} 个")
