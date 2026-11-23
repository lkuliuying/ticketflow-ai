import logging
from unittest.mock import Mock

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from redis.exceptions import ConnectionError as RedisConnectionError

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
        config.refresh_from_db()
        assert config.value == expected
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


@pytest.mark.django_db(transaction=True)
def test_branding_migrations_can_be_called_in_autocommit(migrations):
    site_state = migrations.project_state([SITE_MIGRATION], at_end=False)
    config = site_state.apps.get_model("system", "SystemConfig").objects.create(
        key="WEB_SITE_CONFIG", value={"Title": "xAdmin"}
    )
    department_state = migrations.project_state([DEPARTMENT_MIGRATION], at_end=False)
    department = department_state.apps.get_model("identity", "DeptInfo").objects.create(
        code="xadmin", name="xAdmin管理团队"
    )

    with connection.schema_editor(atomic=False) as editor:
        assert connection.get_autocommit()
        migrations.get_migration(*SITE_MIGRATION).operations[0].code(site_state.apps, editor)
        migrations.get_migration(*DEPARTMENT_MIGRATION).operations[0].code(department_state.apps, editor)
        assert connection.get_autocommit()

    config.refresh_from_db()
    department.refresh_from_db()
    assert config.value["Title"] == "TicketFlow"
    assert department.name == "TicketFlow管理团队"


@pytest.mark.django_db(transaction=True)
def test_site_title_migration_commits_when_redis_is_unavailable(migrations, monkeypatch, caplog):
    state = migrations.project_state([SITE_MIGRATION], at_end=False)
    config = state.apps.get_model("system", "SystemConfig").objects.create(
        key="WEB_SITE_CONFIG", value={"Title": "xAdmin"}
    )
    invalidate = Mock(side_effect=RedisConnectionError("Redis unavailable"))
    monkeypatch.setattr(SysConfig, "invalid_config_cache", invalidate)

    with connection.schema_editor(atomic=False) as editor:
        migrations.get_migration(*SITE_MIGRATION).apply(state, editor)

    config.refresh_from_db()
    assert config.value["Title"] == "TicketFlow"
    invalidate.assert_called_once_with("WEB_SITE_CONFIG")
    assert (
        "system.migrations.0002_rename_default_site_title",
        logging.WARNING,
        "Could not invalidate the site config cache after renaming the default title",
    ) in caplog.record_tuples


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
        root.refresh_from_db()
        assert (root.code, root.name) == ("xadmin", expected)
        migration.unapply(state, editor)

    root.refresh_from_db()
    other.refresh_from_db()
    assert (root.code, root.name) == ("xadmin", expected)
    assert other.name == "xAdmin管理团队"
