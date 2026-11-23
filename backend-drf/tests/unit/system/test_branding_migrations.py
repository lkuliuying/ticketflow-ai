import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from common.core.config import SysConfig

pytestmark = pytest.mark.django_db

SITE_MIGRATION = ("system", "0002_rename_default_site_title")
DEPARTMENT_MIGRATION = ("identity", "0003_rename_default_root_department")


@pytest.fixture
def migrations():
    return MigrationLoader(connection)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"Title": "xAdmin", "Grey": True}, {"Title": "TicketFlow", "Grey": True}),
        ({"Title": "客户服务平台"}, {"Title": "客户服务平台"}),
        ({"Title": "xadmin"}, {"Title": "xadmin"}),
        ({"Title": "xAdmin "}, {"Title": "xAdmin "}),
        ({"Grey": False}, {"Grey": False}),
        (["xAdmin"], ["xAdmin"]),
    ],
)
def test_site_title_migration_matches_only_the_old_default(migrations, value, expected):
    state = migrations.project_state([SITE_MIGRATION], at_end=False)
    config = state.apps.get_model("system", "SystemConfig").objects.create(key="WEB_SITE_CONFIG", value=value)
    migration = migrations.get_migration(*SITE_MIGRATION)

    with connection.schema_editor(atomic=False) as editor:
        migration.apply(state, editor)
        migration.unapply(state, editor)

    config.refresh_from_db()
    assert config.value == expected


def test_site_title_migration_invalidates_warm_config_cache(migrations, django_capture_on_commit_callbacks):
    state = migrations.project_state([SITE_MIGRATION], at_end=False)
    state.apps.get_model("system", "SystemConfig").objects.create(key="WEB_SITE_CONFIG", value={"Title": "xAdmin"})
    assert SysConfig.get_value("WEB_SITE_CONFIG")["Title"] == "xAdmin"

    with django_capture_on_commit_callbacks(execute=True), connection.schema_editor(atomic=False) as editor:
        migrations.get_migration(*SITE_MIGRATION).apply(state, editor)

    assert SysConfig.get_value("WEB_SITE_CONFIG")["Title"] == "TicketFlow"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("xAdmin管理团队", "TicketFlow管理团队"), ("平台运维团队", "平台运维团队")],
)
def test_department_migration_matches_only_the_default_root(migrations, name, expected):
    state = migrations.project_state([DEPARTMENT_MIGRATION], at_end=False)
    departments = state.apps.get_model("identity", "DeptInfo").objects
    root = departments.create(code="xadmin", name=name)
    other = departments.create(code="support", name="xAdmin管理团队")
    migration = migrations.get_migration(*DEPARTMENT_MIGRATION)

    with connection.schema_editor(atomic=False) as editor:
        migration.apply(state, editor)
        migration.unapply(state, editor)

    root.refresh_from_db()
    other.refresh_from_db()
    assert (root.code, root.name) == ("xadmin", expected)
    assert other.name == "xAdmin管理团队"
