from datetime import datetime
from typing import TypedDict
from uuid import UUID

from django.db.models import CharField, F, Prefetch, QuerySet, Value, prefetch_related_objects

from tickets.models import Ticket, TicketComment, TicketLog, Visibility


class TimelineEntry(TypedDict):
    id: UUID
    created_time: datetime
    kind: str
    actor: str
    body: str
    action: str
    from_status: str | None
    to_status: str | None
    visibility: str


def _visible_rows(internal: bool) -> tuple[QuerySet[TicketLog], QuerySet[TicketComment]]:
    logs = TicketLog.objects.all()
    comments = TicketComment.objects.all()
    if not internal:
        logs = logs.filter(internal=False)
        comments = comments.filter(visibility=Visibility.PUBLIC)
    return logs, comments


def timeline_rows(ticket: Ticket, internal: bool) -> QuerySet:
    logs, comments = _visible_rows(internal)
    log_rows = (
        logs.filter(ticket=ticket)
        .order_by()
        .annotate(
            kind=Value("log"),
            actor=F("operator__username"),
            body=F("note"),
            visibility=Value("", output_field=CharField()),
        )
    )
    comment_rows = (
        comments.filter(ticket=ticket)
        .order_by()
        .annotate(
            kind=Value("comment"),
            actor=F("author__username"),
            action=Value("", output_field=CharField()),
            from_status=Value(None, output_field=CharField()),
            to_status=Value(None, output_field=CharField()),
        )
    )
    fields = ("id", "created_time", "kind", "actor", "body", "action", "from_status", "to_status", "visibility")
    return log_rows.values(*fields).union(comment_rows.values(*fields), all=True).order_by("-created_time", "-id")


def first_page(ticket: Ticket, internal: bool) -> dict[str, int | list[TimelineEntry]]:
    size = 20
    logs, comments = _visible_rows(internal)
    prefetch_related_objects(
        [ticket],
        Prefetch("logs", queryset=logs.select_related("operator")[:size], to_attr="timeline_logs"),
        Prefetch("comments", queryset=comments.select_related("author")[:size], to_attr="timeline_comments"),
    )
    entries: list[TimelineEntry] = [
        {
            "id": log.id,
            "created_time": log.created_time,
            "kind": "log",
            "actor": log.operator.username,
            "body": log.note,
            "action": log.action,
            "from_status": log.from_status,
            "to_status": log.to_status,
            "visibility": "",
        }
        for log in ticket.timeline_logs
    ]
    entries.extend(
        {
            "id": row.id,
            "created_time": row.created_time,
            "kind": "comment",
            "actor": row.author.username,
            "body": row.body,
            "action": "",
            "from_status": None,
            "to_status": None,
            "visibility": row.visibility,
        }
        for row in ticket.timeline_comments
    )
    entries.sort(key=lambda row: (row["created_time"], row["id"]), reverse=True)
    return {
        "total": logs.filter(ticket=ticket).count() + comments.filter(ticket=ticket).count(),
        "results": entries[:size],
    }
