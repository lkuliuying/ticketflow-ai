import re
from functools import partial
from uuid import UUID

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, Expression, F, IntegerField, Q, Value, When
from rest_framework.exceptions import NotFound, PermissionDenied

from identity.models import UserInfo
from knowledge.embeddings import embedding_configured, vector_candidates
from knowledge.models import ArticleStatus, KnowledgeArticle
from knowledge.tasks import rebuild_article_chunks
from tickets.models import Status, Ticket
from tickets.policy import TicketAccess
from tickets.services import TicketConflict

ARTICLE_CACHE_KEY_PREFIX = "ticketflow:article:"
CJK_STOP_WORDS = (
    "为什么",
    "怎么办",
    "怎么",
    "如何",
    "什么",
    "请问",
    "一下",
    "无法",
    "不能",
    "我的",
    "这个",
    "那个",
    "还是",
    "可以",
    "没有",
    "已经",
    "出现",
    "问题",
    "时候",
    "提示",
    "一直",
    "需要",
    "帮我",
    "看看",
    "进行",
)
CJK_SPLIT_RE = re.compile(r"[的了吗呢啊吧是在我你他这那和与或都也就还要会到给把被让从对向于]+")
TOKEN_RE = re.compile(r"[\u3400-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9._-]{1,31}")


def article_key(article: KnowledgeArticle) -> str:
    return f"{ARTICLE_CACHE_KEY_PREFIX}{article.pk}:{article.updated_time}"


def load_article_detail(article: KnowledgeArticle) -> None:
    cache_key = article_key(article)
    body = cache.get(cache_key)
    if body is None:
        body = article.body_markdown
        cache.set(cache_key, body, 300)
    article.body_markdown = body
    if article.status == ArticleStatus.PUBLISHED:
        updated = KnowledgeArticle.objects.filter(pk=article.pk, status=ArticleStatus.PUBLISHED).update(
            view_count=F("view_count") + 1
        )
        if updated:
            article.refresh_from_db(fields=["view_count"])


@transaction.atomic
def create_article(
    user: UserInfo, access: TicketAccess, values: dict[str, object], source_ticket_id: UUID | None
) -> KnowledgeArticle:
    if source_ticket_id is not None:
        ticket = access.scope(Ticket.objects.all()).select_for_update().filter(pk=source_ticket_id).first()
        if ticket is None:
            raise NotFound("来源工单不存在")
        if not access.can_archive(ticket):
            raise PermissionDenied("无权转存此工单")
        if ticket.status != Status.CLOSED:
            raise TicketConflict("只有已关闭的工单可以转存")
        if KnowledgeArticle.objects.filter(source_ticket=ticket).exists():
            raise TicketConflict("此工单已转存为知识库文章")
    elif not access.admin:
        raise PermissionDenied("无权创建独立知识库文章")
    article = KnowledgeArticle.objects.create(
        creator=user, modifier=user, dept_belong_id=user.dept_id, source_ticket_id=source_ticket_id, **values
    )
    schedule_article_chunks(article)
    return article


def schedule_article_chunks(article: KnowledgeArticle) -> None:
    transaction.on_commit(partial(rebuild_article_chunks.delay, str(article.pk)), robust=True)


def extract_search_terms(text: str, *, max_terms: int = 16) -> list[str]:
    """Extract ASCII tokens and segmented CJK keywords/bigrams for trigram search."""
    terms: list[str] = []
    seen: set[str] = set()

    def push(token: str) -> None:
        cleaned = token.strip().lower()
        if not cleaned or cleaned in seen:
            return
        if cleaned.isascii() and len(cleaned) < 2:
            return
        seen.add(cleaned)
        terms.append(cleaned)

    for raw in TOKEN_RE.findall(text):
        if raw.isascii():
            if len(raw) >= 3 or raw.upper() in {"AI", "IP", "OS", "AD", "UI", "DB", "VM"}:
                push(raw)
            continue
        trimmed = raw
        for stop in CJK_STOP_WORDS:
            trimmed = trimmed.replace(stop, " ")
        for segment in CJK_SPLIT_RE.split(trimmed):
            for chunk in segment.split():
                if len(chunk) < 2:
                    continue
                if len(chunk) <= 4:
                    push(chunk)
                if len(chunk) >= 3:
                    for idx in range(len(chunk) - 1):
                        push(chunk[idx : idx + 2])
    return terms[:max_terms]


def references_for(ticket: Ticket, limit: int = 5) -> list[dict[str, object]]:
    return references_for_text(f"{ticket.title} {ticket.description[:800]}", category=ticket.category, limit=limit)


def _keyword_references(text: str, *, category: str | None, limit: int) -> list[dict[str, object]]:
    terms = extract_search_terms(text)
    if not terms:
        return []
    vector = SearchVector("title", weight="A", config="simple") + SearchVector(
        "body_markdown", weight="B", config="simple"
    )
    query = SearchQuery(terms[0], config="simple")
    matches = Q(title__icontains=terms[0]) | Q(body_markdown__icontains=terms[0])
    score_expr: Expression = Case(
        When(title__icontains=terms[0], then=Value(2)),
        When(body_markdown__icontains=terms[0], then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    for term in terms[1:]:
        query |= SearchQuery(term, config="simple")
        matches |= Q(title__icontains=term) | Q(body_markdown__icontains=term)
        score_expr = score_expr + Case(
            When(title__icontains=term, then=Value(2)),
            When(body_markdown__icontains=term, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ranked = (
        KnowledgeArticle.objects.filter(matches, status=ArticleStatus.PUBLISHED)
        .annotate(
            term_score=score_expr,
            rank=SearchRank(vector, query),
            same_category=Case(When(category=category, then=Value(1)), default=Value(0), output_field=IntegerField()),
        )
        .order_by("-same_category", "-term_score", "-rank", "-updated_time", "id")
        .values_list("id", "title", "body_markdown")[:limit]
    )
    result: list[dict[str, object]] = []
    for article_id, title, body in ranked:
        lower_body = body.lower()
        start = min((offset for term in terms if (offset := lower_body.find(term)) >= 0), default=0)
        start = max(0, start - 120)
        result.append({"article_id": str(article_id), "title": title, "excerpt": body[start : start + 800]})
    return result


def references_for_text(text: str, *, category: str | None = None, limit: int = 5) -> list[dict[str, object]]:
    keyword_hits = _keyword_references(text, category=category, limit=limit)
    if not embedding_configured():
        return keyword_hits
    vec_hits = vector_candidates(text, limit=limit)
    if not vec_hits:
        return keyword_hits
    scores: dict[str, float] = {}
    items: dict[str, dict[str, object]] = {}
    for rank_idx, row in enumerate(keyword_hits, start=1):
        aid = str(row["article_id"])
        scores[aid] = scores.get(aid, 0.0) + 1.0 / (60 + rank_idx)
        items[aid] = row
    for rank_idx, row in enumerate(vec_hits, start=1):
        aid = str(row["article_id"])
        scores[aid] = scores.get(aid, 0.0) + 1.0 / (60 + rank_idx)
        items.setdefault(aid, {"article_id": aid, "title": row["title"], "excerpt": row["excerpt"]})
    ordered = sorted(scores, key=lambda aid: scores[aid], reverse=True)[:limit]
    return [items[aid] for aid in ordered]
