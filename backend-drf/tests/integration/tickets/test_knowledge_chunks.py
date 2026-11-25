from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import transaction

from knowledge.embeddings import sync_article_chunks
from knowledge.models import ArticleStatus, KnowledgeArticle
from knowledge.services import references_for_text

pytestmark = pytest.mark.django_db


def test_vector_sql_failure_keeps_the_outer_transaction_usable():
    article = KnowledgeArticle.objects.create(
        title="VPN 指南", body_markdown="VPN 重连", status=ArticleStatus.PUBLISHED
    )
    article.chunks.create(
        chunk_index=0, content=article.body_markdown, embedding_vector=[1.0, 0.0], embedding_model="mock"
    )
    with (
        patch("knowledge.embeddings.embedding_config", return_value=("https://example.invalid", "fixture", "mock")),
        patch("knowledge.embeddings.fetch_embeddings", return_value=[[1.0, 0.0, 0.0]]),
        transaction.atomic(),
    ):
        assert references_for_text("VPN 重连")[0]["article_id"] == str(article.pk)
        assert KnowledgeArticle.objects.filter(pk=article.pk).update(view_count=1) == 1
    article.refresh_from_db()
    assert article.view_count == 1


def test_article_publish_queues_rebuild_after_commit(users, client_for, django_capture_on_commit_callbacks):
    article = KnowledgeArticle.objects.create(title="VPN 草稿", body_markdown="重试测试", category="NETWORK")
    with patch("knowledge.services.rebuild_article_chunks.delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = client_for(users["admin"]).patch(
                f"/api/knowledge/articles/{article.pk}", {"status": "PUBLISHED"}, format="json"
            )
            assert response.status_code == 200, response.data
            delay.assert_not_called()
        delay.assert_called_once_with(str(article.pk))


def test_stale_embedding_job_does_not_replace_newer_chunks():
    article = KnowledgeArticle.objects.create(title="VPN 指南", body_markdown="旧版本", status=ArticleStatus.PUBLISHED)

    def edit_while_fetching(_):
        KnowledgeArticle.objects.filter(pk=article.pk).update(body_markdown="新版本")
        article.chunks.create(chunk_index=0, content="新版本")
        return [[1.0, 0.0]]

    with patch("knowledge.embeddings.fetch_embeddings", side_effect=edit_while_fetching):
        assert sync_article_chunks(article.pk) == 0
    assert article.chunks.get().content == "新版本"


def test_backfill_rebuilds_existing_articles_without_duplicate_chunks():
    article = KnowledgeArticle.objects.create(title="VPN 指南", body_markdown="现有文章")
    call_command("rebuild_knowledge_chunks")
    call_command("rebuild_knowledge_chunks")
    assert article.chunks.get().content == "VPN 指南\n\n现有文章"
