from django.db import migrations


def migrate_public_comments(apps, schema_editor):
    TicketComment = apps.get_model("tickets", "TicketComment")
    TicketChatMessage = apps.get_model("tickets", "TicketChatMessage")
    comments = TicketComment.objects.filter(visibility="PUBLIC").order_by("created_time", "id")
    existing_ids = set(TicketChatMessage.objects.values_list("id", flat=True))
    to_create = [
        TicketChatMessage(
            id=comment.id,
            ticket_id=comment.ticket_id,
            sender_id=comment.author_id,
            kind="TEXT",
            content=comment.body,
            created_time=comment.created_time,
        )
        for comment in comments
        if comment.id not in existing_ids
    ]
    if to_create:
        TicketChatMessage.objects.bulk_create(to_create, batch_size=500)
        # auto_now_add overwrites created_time on bulk_create; restore exact timestamps.
        for item, comment in zip(to_create, [c for c in comments if c.id not in existing_ids], strict=True):
            item.created_time = comment.created_time
        TicketChatMessage.objects.bulk_update(to_create, ["created_time"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("tickets", "0010_ticket_attachments_and_chat")]

    operations = [
        migrations.RunPython(migrate_public_comments, migrations.RunPython.noop),
    ]
