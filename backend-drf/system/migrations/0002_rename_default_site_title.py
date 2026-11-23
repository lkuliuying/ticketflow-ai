import logging

from django.db import DEFAULT_DB_ALIAS, migrations, transaction
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def _invalidate_site_config_cache():
    from common.core.config import SysConfig

    try:
        SysConfig.invalid_config_cache("WEB_SITE_CONFIG")
    except RedisError:
        logger.warning("Could not invalidate the site config cache after renaming the default title", exc_info=True)


def rename_default_site_title(apps, schema_editor):
    alias = schema_editor.connection.alias
    with transaction.atomic(using=alias):
        configs = apps.get_model("system", "SystemConfig").objects.using(alias)
        config = configs.select_for_update().filter(key="WEB_SITE_CONFIG", value__Title="xAdmin").first()
        if config is None:
            return

        configs.filter(pk=config.pk).update(value={**config.value, "Title": "TicketFlow"})
        if alias == DEFAULT_DB_ALIAS:
            transaction.on_commit(_invalidate_site_config_cache, using=alias)


class Migration(migrations.Migration):
    dependencies = [("system", "0001_initial")]

    operations = [migrations.RunPython(rename_default_site_title, migrations.RunPython.noop)]
