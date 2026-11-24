from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from identity.models import DeptInfo, UserInfo, UserRole
from ops.legacy.structure import _run_data_cleanups
from settings.models import Setting
from tickets.models import Status, TicketLog
from tickets.policy import ADMIN_ROLE, AGENT_ROLE, REQUESTER_ROLE

BACKFILL = import_module("tickets.migrations.0003_backfill_ticket_assignments")
BUSINESS_ROLES = import_module("tickets.migrations.0004_business_roles_and_registration")


@pytest.fixture
def users(db):
    """迁移通过 ORM 和历史模型运行，只需要旧记录涉及的角色和用户。"""
    dept = DeptInfo.objects.create(code="migration-support", name="迁移测试技能组")
    accounts = {}
    for name, code in (("requester", REQUESTER_ROLE), ("agent", AGENT_ROLE), ("admin", ADMIN_ROLE)):
        accounts[name] = UserInfo.objects.create_user(username=name, dept=dept)
        accounts[name].roles.add(UserRole.objects.create(code=code, name=name))
    return accounts


@pytest.mark.django_db
def test_existing_assignments_backfill_from_last_log_and_known_assignee(users, make_ticket):
    active = make_ticket(assignee=users["agent"])
    log = TicketLog.objects.create(ticket=active, action="ASSIGN", operator=users["admin"])
    closed = make_ticket(assignee=users["agent"], status=Status.CLOSED)
    closure = TicketLog.objects.create(
        ticket=closed, action="TRANSITION", to_status=Status.CLOSED, operator=users["requester"]
    )
    unassigned = make_ticket()
    TicketLog.objects.create(ticket=unassigned, action="ASSIGN", operator=users["admin"])
    reopened = make_ticket(assignee=users["agent"], status=Status.REOPENED)
    previous_close = TicketLog.objects.create(
        ticket=reopened, action="TRANSITION", to_status=Status.CLOSED, operator=users["requester"]
    )
    reopening = TicketLog.objects.create(
        ticket=reopened, action="TRANSITION", to_status=Status.REOPENED, operator=users["requester"]
    )

    with connection.schema_editor(atomic=False) as editor:
        BACKFILL.backfill_ticket_assignments(apps, editor)

    current = active.assignments.get()
    assert current.assignee_id == active.assignee_id
    assert current.assigned_by_id == users["admin"].pk
    assert (current.started_at, current.ended_at) == (log.created_time, None)
    completed = closed.assignments.get()
    assert (completed.started_at, completed.ended_at, completed.end_reason) == (
        closed.created_time,
        closure.created_time,
        "CLOSED_OUT",
    )
    assert not unassigned.assignments.exists()
    assert reopened.assignments.count() == 2
    assert reopened.assignments.get(end_reason="CLOSED_OUT").ended_at == previous_close.created_time
    assert reopened.assignments.get(ended_at__isnull=True).started_at == reopening.created_time


@pytest.mark.django_db
def test_retired_role_grants_are_merged_and_legacy_registration_setting_is_closed(users):
    admin = UserRole.objects.get(code="ticketflow_admin")
    admin.name = "工单管理员"
    admin.save(update_fields=["name"])
    legacy = UserRole.objects.create(code="ticketflow_kb_editor", name="知识维护人员")
    team = DeptInfo.objects.create(code="legacy-team", name="原授权技能组")
    editor = UserInfo.objects.create_user(username="legacy-editor", dept=team)
    editor.roles.add(legacy, admin)
    team.roles.add(legacy)
    Setting.objects.create(name="SECURITY_REGISTER_ACCESS_ENABLED", value="true", is_active=True)
    historical = (
        MigrationExecutor(connection).loader.project_state([("tickets", "0004_business_roles_and_registration")]).apps
    )

    with connection.schema_editor(atomic=False) as schema:
        BUSINESS_ROLES.migrate_roles(historical, schema)
        BUSINESS_ROLES.close_registration(historical, schema)

    admin.refresh_from_db()
    assert admin.name == "管理员"
    assert not UserRole.all_objects.filter(pk=legacy.pk).exists()
    assert list(editor.roles.all()) == list(team.roles.all()) == [admin]
    assert Setting.objects.get(name="SECURITY_REGISTER_ACCESS_ENABLED").cleaned_value is False


@pytest.mark.django_db
def test_structure_alignment_applies_pending_ticket_data_without_repeating_applied_changes(users, make_ticket):
    ticket = make_ticket(assignee=users["agent"])
    registration, _ = Setting.objects.update_or_create(
        name="SECURITY_REGISTER_ACCESS_ENABLED", defaults={"value": "true", "is_active": True}
    )
    nodes = [
        ("tickets", "0003_backfill_ticket_assignments"),
        ("tickets", "0004_business_roles_and_registration"),
    ]
    loader = MigrationExecutor(connection).loader

    with connection.schema_editor(atomic=False) as schema:
        assert _run_data_cleanups(loader, schema, nodes) == ([], [])
        registration.refresh_from_db()
        assert registration.cleaned_value is True
        assert not ticket.assignments.exists()

        recorder = MigrationRecorder(connection)
        for node in nodes:
            recorder.record_unapplied(*node)
        expected = (["backfill_ticket_assignments", "migrate_roles", "close_registration"], [])
        assert _run_data_cleanups(loader, schema, nodes) == expected
        original = ticket.assignments.get()

        # 结构阶段成功后，后续步骤可能在写账本前中断。重试应保留既有历史。
        assert _run_data_cleanups(loader, schema, nodes) == expected
        assert ticket.assignments.get().pk == original.pk
        registration.refresh_from_db()
        assert registration.cleaned_value is False
