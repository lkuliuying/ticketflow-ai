import logging

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import DatabaseError, migrations, transaction
from django.db.models.functions import Upper

logger = logging.getLogger(__name__)
INDEXES = (
    GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="tf_kb_title_trgm_idx"),
    GinIndex(OpClass(Upper("body_markdown"), name="gin_trgm_ops"), name="tf_kb_body_trgm_idx"),
)


def create_trigram_extension(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    try:
        with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except DatabaseError:
        logger.warning("无法创建 pg_trgm 扩展，知识库检索将继续使用普通查询。", exc_info=True)


def add_trigram_indexes(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_opclass WHERE opcname = 'gin_trgm_ops' AND pg_opclass_is_visible(oid))"
        )
        if not cursor.fetchone()[0]:
            logger.warning("gin_trgm_ops 不可用，跳过知识库 trigram 索引。")
            return
    article = apps.get_model("knowledge", "KnowledgeArticle")
    for index in INDEXES:
        schema_editor.add_index(article, index)


def remove_trigram_indexes(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    article = apps.get_model("knowledge", "KnowledgeArticle")
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, article._meta.db_table)
    for index in reversed(INDEXES):
        if constraints.get(index.name, {}).get("index"):
            schema_editor.remove_index(article, index)


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0002_initial")]

    operations = [
        migrations.RunPython(create_trigram_extension, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_trigram_indexes, remove_trigram_indexes)],
            state_operations=[migrations.AddIndex(model_name="knowledgearticle", index=index) for index in INDEXES],
        ),
    ]
