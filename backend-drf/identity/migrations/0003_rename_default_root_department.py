from django.db import migrations, transaction


def rename_default_root_department(apps, schema_editor):
    alias = schema_editor.connection.alias
    with transaction.atomic(using=alias):
        departments = apps.get_model("identity", "DeptInfo").objects.using(alias)
        departments.filter(code="xadmin", parent__isnull=True, name="xAdmin管理团队").update(name="TicketFlow管理团队")


class Migration(migrations.Migration):
    dependencies = [("identity", "0002_initial")]

    operations = [migrations.RunPython(rename_default_root_department, migrations.RunPython.noop)]
