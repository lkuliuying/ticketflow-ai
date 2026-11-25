from uuid import UUID

from celery import shared_task

from knowledge.embeddings import sync_article_chunks


@shared_task(ignore_result=True)
def rebuild_article_chunks(article_id: str) -> None:
    sync_article_chunks(UUID(article_id))
