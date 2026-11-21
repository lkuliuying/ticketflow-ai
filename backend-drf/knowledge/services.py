import re
from uuid import UUID

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from rest_framework.exceptions import NotFound, PermissionDenied

from identity.models import UserInfo
from knowledge.models import ArticleStatus, KnowledgeArticle
from tickets.models import Status, Ticket
from tickets.policy import TicketAccess
from tickets.services import TicketConflict

ARTICLE_CACHE_KEY_PREFIX = "ticketflow:article:"


def article_key(article: KnowledgeArticle) -> str:
    return f"{ARTICLE_CACHE_KEY_PREFIX}{article.pk}:{article.updated_time}"


def count_article_view(article: KnowledgeArticle) -> None:
    cache_key = article_key(article)
    body = cache.get(cache_key)
    if body is None:
        body = article.body_markdown
        cache.set(cache_key, body, 300)
    article.body_markdown = body
    KnowledgeArticle.objects.filter(pk=article.pk).update(view_count=F("view_count") + 1)
    article.refresh_from_db(fields=["view_count"])


@transaction.atomic
def create_article(
    user: UserInfo, access: TicketAccess, values: dict[str, object], source_ticket_id: UUID | None
) -> KnowledgeArticle:
    if source_ticket_id is not None:
        ticket = access.scope(Ticket.objects.all()).select_for_update().filter(pk=source_ticket_id).first()
        if ticket is None:
            raise NotFound("来源工单不存在")
        if not access.can_handle(ticket):
            raise PermissionDenied("无权转存此工单")
        if ticket.status != Status.CLOSED:
            raise TicketConflict("只有已关闭的工单可以转存")
        if KnowledgeArticle.objects.filter(source_ticket=ticket).exists():
            raise TicketConflict("此工单已转存为知识库文章")
    elif not access.admin:
        raise PermissionDenied("无权创建独立知识库文章")
    return KnowledgeArticle.objects.create(
        creator=user, modifier=user, dept_belong_id=user.dept_id, source_ticket_id=source_ticket_id, **values
    )


def references_for(ticket: Ticket, limit: int = 5) -> list[dict[str, object]]:
    words = re.findall(r"[\u3400-\u9fff]{2,12}|[A-Za-z0-9]{3,32}", f"{ticket.title} {ticket.description[:800]}")
    terms = list(dict.fromkeys(word.lower() for word in words))[:12]
    if not terms:
        return []
    vector = SearchVector("title", weight="A", config="simple") + SearchVector(
        "body_markdown", weight="B", config="simple"
    )
    query = SearchQuery(terms[0], config="simple")
    matches = Q(title__icontains=terms[0]) | Q(body_markdown__icontains=terms[0])
    for term in terms[1:]:
        query |= SearchQuery(term, config="simple")
        matches |= Q(title__icontains=term) | Q(body_markdown__icontains=term)
    ranked = (
        KnowledgeArticle.objects.filter(status=ArticleStatus.PUBLISHED)
        .annotate(
            vector=vector,
            rank=SearchRank(vector, query),
            same_category=Case(
                When(category=ticket.category, then=Value(1)), default=Value(0), output_field=IntegerField()
            ),
        )
        .filter(matches | Q(vector=query))
        .order_by("-same_category", "-rank", "-updated_time", "id")
        .values_list("id", "title", "body_markdown")[:limit]
    )
    result = []
    for article_id, title, body in ranked:
        lower_body = body.lower()
        start = min((offset for term in terms if (offset := lower_body.find(term)) >= 0), default=0)
        start = max(0, start - 120)
        result.append({"article_id": str(article_id), "title": title, "excerpt": body[start : start + 800]})
    return result
