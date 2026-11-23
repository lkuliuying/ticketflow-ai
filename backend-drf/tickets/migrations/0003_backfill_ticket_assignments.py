from django.db import migrations
from django.db.models import OuterRef, Prefetch, Subquery


def segments(ticket, assignment_model):
    started = ticket.assigned_at or ticket.created_time
    assigned_by = ticket.assigned_by_id
    active = True
    for event in ticket.lifecycle:
        if event.created_time < started:
            continue
        if active and event.to_status == "CLOSED":
            yield assignment_model(
                ticket_id=ticket.pk,
                assignee_id=ticket.assignee_id,
                assigned_by_id=assigned_by,
                started_at=started,
                ended_at=event.created_time,
                end_reason="CLOSED_OUT",
            )
            active = False
            started, assigned_by = event.created_time, None
        elif not active and event.to_status == "REOPENED":
            started, assigned_by, active = event.created_time, None, True

    closed = ticket.status == "CLOSED"
    if active or not closed:
        if not active:
            started = max(started, ticket.updated_time)
        yield assignment_model(
            ticket_id=ticket.pk,
            assignee_id=ticket.assignee_id,
            assigned_by_id=assigned_by,
            started_at=started,
            ended_at=max(started, ticket.updated_time) if closed else None,
            end_reason="CLOSED_OUT" if closed else "",
        )


def backfill_ticket_assignments(apps, schema_editor):
    database = schema_editor.connection.alias
    tickets = apps.get_model("tickets", "Ticket").objects.using(database)
    logs = apps.get_model("tickets", "TicketLog").objects.using(database)
    assignments = apps.get_model("tickets", "TicketAssignment").objects.using(database)
    events = logs.filter(ticket_id=OuterRef("pk")).order_by("-created_time", "-pk")
    last_assign = events.filter(action="ASSIGN")
    lifecycle = logs.filter(action="TRANSITION", to_status__in=("CLOSED", "REOPENED")).order_by("created_time", "pk")
    rows = (
        tickets.filter(assignee_id__isnull=False)
        .exclude(pk__in=assignments.values("ticket_id"))
        .annotate(
            assigned_at=Subquery(last_assign.values("created_time")[:1]),
            assigned_by_id=Subquery(last_assign.values("operator_id")[:1]),
        )
        .prefetch_related(Prefetch("logs", queryset=lifecycle, to_attr="lifecycle"))
    )
    batch = []
    for row in rows.iterator(chunk_size=1000):
        batch.extend(segments(row, assignments.model))
        if len(batch) >= 1000:
            assignments.bulk_create(batch)
            batch.clear()
    assignments.bulk_create(batch)


class Migration(migrations.Migration):
    dependencies = [("tickets", "0002_alter_ticketlog_operator_ticketassignment")]

    operations = [migrations.RunPython(backfill_ticket_assignments, migrations.RunPython.noop)]
