from datetime import datetime
from typing import Any
from uuid import UUID

from django.apps import apps
from django.db import transaction
from django.db.models import Count, Q
from rest_framework.exceptions import NotFound, PermissionDenied

from tickets.models import AssistantFeedback, AssistantMessage, AssistantSession, Category
from tickets.policy import TicketAccess

HISTORY_TURNS = 10
HISTORY_CHARACTERS = 8000


def require_employee(access: TicketAccess) -> None:
    if not access.employee:
        raise PermissionDenied("仅普通员工可使用 AI 助手")


def owned_session(user_id: int, session_id: UUID, *, lock: bool = False) -> AssistantSession:
    queryset = AssistantSession.objects.filter(user_id=user_id, pk=session_id)
    if lock:
        queryset = queryset.select_for_update()
    session = queryset.first()
    if session is None:
        raise NotFound("会话不存在")
    return session


def conversation_context(session: AssistantSession) -> dict[str, object]:
    questions = session.messages.filter(role=AssistantMessage.Role.USER).select_related("answer")
    turns: list[list[dict[str, str]]] = []
    remaining = HISTORY_CHARACTERS
    for question in questions.order_by("-created_time", "-pk")[:HISTORY_TURNS]:
        content = question.content[:remaining]
        remaining -= len(content)
        turn = [{"role": AssistantMessage.Role.USER, "content": content}]
        answer = getattr(question, "answer", None)
        if remaining and answer is not None and answer.status == AssistantMessage.Status.COMPLETE:
            content = answer.content[:remaining]
            turn.append({"role": AssistantMessage.Role.ASSISTANT, "content": content})
            remaining -= len(content)
        turns.append(turn)
        if not remaining:
            break
    return {"history": [item for turn in reversed(turns) for item in turn], "categories": list(Category.values)}


@transaction.atomic
def record_question(user_id: int, session_id: UUID, message: str) -> dict[str, object]:
    session = owned_session(user_id, session_id, lock=True)
    context = conversation_context(session)
    references = []
    if apps.is_installed("knowledge"):
        from knowledge.services import references_for_text

        references = references_for_text(message)
    question = AssistantMessage.objects.create(session=session, role=AssistantMessage.Role.USER, content=message)
    session.save(update_fields=["updated_time"])
    return {**context, "user_message_id": question.pk, "references": references}


@transaction.atomic
def record_answer(
    user_id: int,
    session_id: UUID,
    user_message_id: UUID,
    content: str,
    references: list[dict[str, Any]],
    status: str,
) -> UUID:
    session = owned_session(user_id, session_id, lock=True)
    question = session.messages.filter(pk=user_message_id, role=AssistantMessage.Role.USER).first()
    if question is None:
        raise NotFound("问题不存在")
    answer, created = AssistantMessage.objects.get_or_create(
        user_message=question,
        defaults={
            "session": session,
            "role": AssistantMessage.Role.ASSISTANT,
            "content": content,
            "references": [{**ref, "article_id": str(ref["article_id"])} for ref in references],
            "status": status,
        },
    )
    if created:
        session.save(update_fields=["updated_time"])
    return answer.pk


@transaction.atomic
def save_feedback(
    user_id: int, session_id: UUID, message_id: UUID, vote: str, reason: str | None, comment: str
) -> AssistantFeedback:
    session = owned_session(user_id, session_id, lock=True)
    answer = session.messages.filter(pk=message_id, role=AssistantMessage.Role.ASSISTANT).first()
    if answer is None:
        raise NotFound("回答不存在")
    feedback, _ = AssistantFeedback.objects.update_or_create(
        message=answer, defaults={"vote": vote, "reason": reason, "comment": comment}
    )
    return feedback


def date_filter(field: str, created_from: datetime | None = None, created_to: datetime | None = None) -> Q:
    result = Q()
    if created_from is not None:
        result &= Q(**{f"{field}__gte": created_from})
    if created_to is not None:
        result &= Q(**{f"{field}__lte": created_to})
    return result


def assistant_stats(created_from: datetime | None = None, created_to: datetime | None = None) -> dict[str, int]:
    created = date_filter("created_time", created_from, created_to)
    votes = AssistantFeedback.objects.filter(date_filter("updated_time", created_from, created_to)).aggregate(
        up=Count("pk", filter=Q(vote=AssistantFeedback.Vote.UP)),
        down=Count("pk", filter=Q(vote=AssistantFeedback.Vote.DOWN)),
    )
    return {
        "sessions": AssistantSession.all_objects.filter(created).count(),
        "questions": AssistantMessage.objects.filter(created, role=AssistantMessage.Role.USER).count(),
        **votes,
        "handoffs": AssistantSession.all_objects.filter(
            date_filter("ticket__created_time", created_from, created_to), ticket__isnull=False
        ).count(),
    }
