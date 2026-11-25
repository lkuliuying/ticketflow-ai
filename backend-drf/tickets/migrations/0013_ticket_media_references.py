import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("file", "0003_uploadfile_upload_source"),
        ("tickets", "0012_flatten_ticketflow_menus"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketattachment",
            name="file",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="ticket_attachments", to="file.uploadfile"
            ),
        ),
        migrations.AlterField(
            model_name="ticketchatmessage",
            name="attachment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ticket_chat_messages",
                to="file.uploadfile",
            ),
        ),
    ]
