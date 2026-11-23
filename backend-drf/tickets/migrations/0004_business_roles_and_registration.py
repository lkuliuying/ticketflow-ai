from django.db import migrations

ADMIN_ROLE_ID = "d2431bc0-217a-49eb-a6fa-000000000003"
REGISTER_SETTING = "SECURITY_REGISTER_ACCESS_ENABLED"


def migrate_roles(apps, schema_editor):
    database = schema_editor.connection.alias
    roles = apps.get_model("identity", "UserRole")._base_manager.using(database)
    active = roles.filter(deleted_at__isnull=True)
    for code, old_name, name in (
        ("admin", "管理员", "平台管理员"),
        ("ticketflow_requester", "工单提交人", "普通员工"),
        ("ticketflow_agent", "工单处理人", "技术员"),
        ("ticketflow_admin", "工单管理员", "管理员"),
    ):
        active.filter(code=code, name=old_name).update(name=name)

    editor = active.filter(code="ticketflow_kb_editor").first()
    if editor is not None:
        admin, _ = active.get_or_create(code="ticketflow_admin", defaults={"id": ADMIN_ROLE_ID, "name": "管理员"})
        for model_name in ("UserInfo", "DeptInfo"):
            model = apps.get_model("identity", model_name)
            for member in model._base_manager.using(database).filter(roles=editor).iterator(chunk_size=1000):
                member.roles.add(admin)
    roles.filter(code__in=("ticketflow_kb_editor", "ticketflow_demo_dispatch")).delete()


def close_registration(apps, schema_editor):
    setting = apps.get_model("settings", "Setting")
    setting.objects.using(schema_editor.connection.alias).filter(name=REGISTER_SETTING).update(
        value="false", encrypted=False, is_active=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0003_rename_default_root_department"),
        ("settings", "0001_initial"),
        ("tickets", "0003_backfill_ticket_assignments"),
    ]

    operations = [
        migrations.RunPython(migrate_roles, migrations.RunPython.noop),
        migrations.RunPython(close_registration, migrations.RunPython.noop),
    ]
