from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from identity.models import DeptInfo, UserInfo, UserRole
from settings.models import Setting
from tickets.models import Status, TicketLog

BACKFILL = import_module("tickets.migrations.0003_backfill_ticket_assignments")
BUSINESS_ROLES = import_module("tickets.migrations.0004_business_roles_and_registration")


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
        BACKFILL.backfill(apps, editor)

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
