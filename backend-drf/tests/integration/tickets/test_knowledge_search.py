import json
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from knowledge.models import ArticleStatus, KnowledgeArticle
from knowledge.services import references_for
from tickets.models import Category, Ticket

pytestmark = pytest.mark.django_db


def test_references_match_title_and_body_substrings_with_both_trigram_indexes():
    title_match = KnowledgeArticle.objects.create(
        title="PrefixVPNGateway", category=Category.NETWORK, status=ArticleStatus.PUBLISHED
    )
    body_match = KnowledgeArticle.objects.create(
        title="连接说明", body_markdown="使用 extendedVpnConfig 配置连接", status=ArticleStatus.PUBLISHED
    )
    KnowledgeArticle.objects.create(title="VPN 草稿", category=Category.NETWORK)
    KnowledgeArticle.objects.bulk_create(
        KnowledgeArticle(
            title=f"Account guide {i}",
            body_markdown="Account recovery and password reset instructions.",
            status=ArticleStatus.PUBLISHED,
        )
        for i in range(3000)
    )
    with connection.cursor() as cursor:
        # 模拟批量导入后清理 GIN 待处理页的稳定查询计划。
        cursor.execute("SELECT gin_clean_pending_list('tf_kb_title_trgm_idx')")
        cursor.execute("SELECT gin_clean_pending_list('tf_kb_body_trgm_idx')")
        cursor.execute("ANALYZE knowledge_knowledgearticle")
    ticket = Ticket(title="VPN", description="", category=Category.NETWORK)
    with CaptureQueriesContext(connection) as captured:
        results = references_for(ticket)
    assert [row["article_id"] for row in results] == [str(title_match.pk), str(body_match.pk)]
    assert results[1]["excerpt"] == body_match.body_markdown
    assert references_for(Ticket(title="配置连接", description="")) == [results[1]]

    with connection.cursor() as cursor:
        cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {captured[0]['sql']}")
        plan = cursor.fetchone()[0]
    if isinstance(plan, str):
        plan = json.loads(plan)
    assert index_names(plan[0]["Plan"]) >= {"tf_kb_title_trgm_idx", "tf_kb_body_trgm_idx"}, plan


def index_names(plan: dict[str, Any]) -> set[str]:
    names = {plan["Index Name"]} if "Index Name" in plan else set()
    for child in plan.get("Plans", ()):
        names.update(index_names(child))
    return names
