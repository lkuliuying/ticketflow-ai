from django.db import DEFAULT_DB_ALIAS, migrations, transaction


def rename_default_site_title(apps, schema_editor):
    alias = schema_editor.connection.alias
    configs = apps.get_model("system", "SystemConfig").objects.using(alias)
    config = configs.select_for_update().filter(key="WEB_SITE_CONFIG", value__Title="xAdmin").first()
    if config is None:
        return

    configs.filter(pk=config.pk).update(value={**config.value, "Title": "TicketFlow"})
    if alias == DEFAULT_DB_ALIAS:
        from common.core.config import SysConfig

        transaction.on_commit(lambda: SysConfig.invalid_config_cache("WEB_SITE_CONFIG"), using=alias)


class Migration(migrations.Migration):
    dependencies = [("system", "0001_initial")]

    operations = [migrations.RunPython(rename_default_site_title, migrations.RunPython.noop)]
