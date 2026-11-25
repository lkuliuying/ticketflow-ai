import logging
from typing import Any
from uuid import UUID

import requests
from django.conf import settings
from django.db import DatabaseError
from pgvector.django import CosineDistance

from knowledge.models import ArticleStatus, KnowledgeArticle, KnowledgeChunk

logger = logging.getLogger(__name__)
CHUNK_MAX_CHARS = 800
CHUNK_OVERLAP = 120
EMBEDDING_TIMEOUT = 5.0


def embedding_config() -> tuple[str, str, str]:
    base_url = str(getattr(settings, "TICKETFLOW_EMBEDDING_BASE_URL", "") or "").strip().rstrip("/")
    api_key = str(getattr(settings, "TICKETFLOW_EMBEDDING_API_KEY", "") or "").strip()
    model = str(getattr(settings, "TICKETFLOW_EMBEDDING_MODEL", "") or "").strip()
    return base_url, api_key, model


def embedding_configured() -> bool:
    base_url, api_key, model = embedding_config()
    return bool(base_url and api_key and model)


def split_markdown_chunks(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, max_chars - overlap)
            for start in range(0, len(para), step):
                piece = para[start : start + max_chars].strip()
                if piece:
                    chunks.append(piece)
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:].strip() if overlap and len(current) > overlap else ""
            current = f"{tail}\n\n{para}".strip() if tail and len(tail) + len(para) + 2 <= max_chars else para
    if current:
        chunks.append(current)
    return chunks


def fetch_embeddings(texts: list[str]) -> list[list[float]] | None:
    if not texts or not embedding_configured():
        return None
    base_url, api_key, model = embedding_config()
    try:
        response = requests.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": texts},
            timeout=EMBEDDING_TIMEOUT,
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        rows.sort(key=lambda item: int(item.get("index", 0)))
        vectors = [item["embedding"] for item in rows if isinstance(item.get("embedding"), list)]
        return vectors if len(vectors) == len(texts) else None
    except Exception:
        logger.warning("向量生成失败，已自动回退到关键词检索。", exc_info=True)
        return None


def sync_article_chunks(article: KnowledgeArticle) -> int:
    """Rebuild markdown chunks (and optional pgvector embeddings) for an article."""
    full_text = f"{article.title}\n\n{article.body_markdown}".strip()
    pieces = split_markdown_chunks(full_text)
    _, _, model = embedding_config()
    vectors = fetch_embeddings(pieces) if article.status == ArticleStatus.PUBLISHED else None
    article.chunks.all().delete()
    rows = [
        KnowledgeChunk(
            article=article,
            chunk_index=idx,
            content=piece,
            embedding_vector=vectors[idx] if vectors is not None else None,
            embedding_model=model if vectors is not None else "",
        )
        for idx, piece in enumerate(pieces)
    ]
    if rows:
        KnowledgeChunk.objects.bulk_create(rows)
    return len(rows)


def vector_candidates(text: str, *, category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Query pgvector cosine similarity across published chunks when configured."""
    if not embedding_configured():
        return []
    vectors = fetch_embeddings([text[:2000]])
    if not vectors:
        return []
    _, _, model = embedding_config()
    query_vec = vectors[0]
    try:
        chunks = (
            KnowledgeChunk.objects.filter(
                article__status=ArticleStatus.PUBLISHED,
                embedding_vector__isnull=False,
                embedding_model=model,
            )
            .select_related("article")
            .annotate(distance=CosineDistance("embedding_vector", query_vec))
            .order_by("distance")[: limit * 2]
        )
        seen: set[UUID] = set()
        results: list[dict[str, Any]] = []
        for chunk in chunks:
            if chunk.article_id in seen:
                continue
            seen.add(chunk.article_id)
            results.append(
                {
                    "article_id": str(chunk.article_id),
                    "title": chunk.article.title,
                    "excerpt": chunk.content[:800],
                    "same_category": int(category is not None and chunk.article.category == category),
                }
            )
            if len(results) >= limit:
                break
        return results
    except DatabaseError:
        logger.warning("pgvector 查询不可用，已回退到关键词检索。", exc_info=True)
        return []
