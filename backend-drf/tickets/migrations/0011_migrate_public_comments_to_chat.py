from itertools import batched

from django.db import migrations


def migrate_public_comments(apps, schema_editor):
    TicketComment = apps.get_model("tickets", "TicketComment")
    TicketChatMessage = apps.get_model("tickets", "TicketChatMessage")
    alias = schema_editor.connection.alias
    comments = TicketComment.objects.using(alias).filter(visibility="PUBLIC").order_by("id")
    messages = TicketChatMessage.objects.using(alias)
    for batch in batched(comments.iterator(chunk_size=500), 500, strict=False):
        existing = set(messages.filter(pk__in=[row.pk for row in batch]).values_list("pk", flat=True))
        pending = [row for row in batch if row.pk not in existing]
        created = messages.bulk_create(
            TicketChatMessage(
                id=row.pk, ticket_id=row.ticket_id, sender_id=row.author_id, kind="TEXT", content=row.body
            )
            for row in pending
        )
        # auto_now_add assigns the migration time on insert.
        for item, comment in zip(created, pending, strict=True):
            item.created_time = comment.created_time
        messages.bulk_update(created, ["created_time"])


class Migration(migrations.Migration):
    dependencies = [("tickets", "0010_ticket_attachments_and_chat")]

    operations = [
        migrations.RunPython(migrate_public_comments, migrations.RunPython.noop),
    ]
