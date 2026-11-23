from uuid import UUID

from django.conf import settings
from django.db import migrations
from django.db.models import Q


def import_category_routes(apps, schema_editor):
    alias = schema_editor.connection.alias
    Department = apps.get_model("identity", "DeptInfo")
    User = apps.get_model("identity", "UserInfo")
    Route = apps.get_model("tickets", "CategoryRoute")
    departments = Department.objects.using(alias)
    technician_groups = (
        User.objects.using(alias)
        .filter(roles__code="ticketflow_agent", is_superuser=False, deleted_at__isnull=True)
        .order_by()
        .values("dept_id")
    )
    departments.filter(
        Q(code__in=("ticketflow_support", "ticketflow_demo_network")) | Q(pk__in=technician_groups)
    ).update(is_ticketflow_skill_group=True)

    categories = dict(Route._meta.get_field("category").choices)
    configured = getattr(settings, "TICKETFLOW_CATEGORY_DEPARTMENTS", {})
    for category, department_id in configured.items():
        if category not in categories or not department_id:
            continue
        try:
            pk = UUID(str(department_id))
        except ValueError:
            continue
        department = departments.filter(pk=pk, is_active=True)
        if department.update(is_ticketflow_skill_group=True):
            Route.objects.using(alias).get_or_create(category=category, defaults={"skill_group_id": pk})


class Migration(migrations.Migration):
    dependencies = [("tickets", "0006_categoryroute")]

    operations = [migrations.RunPython(import_category_routes, migrations.RunPython.noop)]
