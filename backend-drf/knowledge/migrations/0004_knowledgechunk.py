import logging
import uuid

import django.db.models.deletion
import pgvector.django.vector
from django.db import DatabaseError, migrations, models, transaction

logger = logging.getLogger(__name__)


def create_vector_extension(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    try:
        with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except DatabaseError:
        logger.warning("无法创建 vector 扩展，知识库检索将回退到关键词与 trigram 通道。", exc_info=True)


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0003_article_trigram_indexes")]

    operations = [
        migrations.RunPython(create_vector_extension, migrations.RunPython.noop),
        migrations.CreateModel(
            name="KnowledgeChunk",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False, verbose_name="ID")),
                ("chunk_index", models.PositiveIntegerField()),
                ("content", models.TextField()),
                ("embedding_vector", pgvector.django.vector.VectorField(blank=True, editable=False, null=True)),
                ("embedding_model", models.CharField(blank=True, default="", max_length=128)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="knowledge.knowledgearticle",
                    ),
                ),
            ],
            options={
                "verbose_name": "知识分块",
                "ordering": ("article", "chunk_index"),
                "indexes": [models.Index(fields=["article", "chunk_index"], name="tf_kb_chunk_order_idx")],
                "constraints": [models.UniqueConstraint(fields=("article", "chunk_index"), name="tf_kb_chunk_once")],
            },
        ),
    ]
