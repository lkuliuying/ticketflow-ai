import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("file", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0009_ticket_trigram_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketAttachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False, verbose_name="ID")),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_time", models.DateTimeField(auto_now_add=True)),
                (
                    "file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="file.uploadfile"
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="tickets.ticket"
                    ),
                ),
                (
                    "uploader",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "工单图片附件",
                "ordering": ("sort_order", "created_time", "id"),
                "constraints": [models.UniqueConstraint(fields=("ticket", "file"), name="tf_ticket_attachment_once")],
            },
        ),
        migrations.CreateModel(
            name="TicketChatMessage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("TEXT", "文本"), ("IMAGE", "图片"), ("VIDEO", "视频"), ("SYSTEM", "系统")],
                        default="TEXT",
                        max_length=8,
                    ),
                ),
                ("content", models.TextField(blank=True, default="")),
                ("media_meta", models.JSONField(blank=True, default=dict)),
                ("media_expired", models.BooleanField(default=False)),
                ("client_msg_id", models.CharField(blank=True, default="", max_length=64)),
                ("created_time", models.DateTimeField(auto_now_add=True)),
                (
                    "attachment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="file.uploadfile",
                    ),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="chat_messages", to="tickets.ticket"
                    ),
                ),
            ],
            options={
                "verbose_name": "工单排查消息",
                "ordering": ("created_time", "id"),
                "indexes": [models.Index(fields=["ticket", "created_time", "id"], name="tf_chat_msg_ticket_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("client_msg_id", ""), _negated=True),
                        fields=("ticket", "sender", "client_msg_id"),
                        name="tf_chat_msg_client_once",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="TicketChatReadState",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_read_time", models.DateTimeField()),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_read_states",
                        to="tickets.ticket",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "工单会话已读游标",
                "indexes": [models.Index(fields=["user", "ticket"], name="tf_chat_read_user_idx")],
                "constraints": [models.UniqueConstraint(fields=("ticket", "user"), name="tf_chat_read_once")],
            },
        ),
    ]
