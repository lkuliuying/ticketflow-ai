import json
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import OperationLog
from common.base.crypto import AESCipherV2
from common.cache.storage import UserTokenRevokedCache
from common.core.auth.authentication import ServerRefreshToken
from identity.models import DeptInfo, UserInfo, UserRole, UserSession
from tickets.models import Category, CategoryRoute, Status, TicketAssignment
from tickets.policy import AGENT_ROLE, REQUESTER_ROLE
from tickets.services import create_ticket

ACCOUNTS = "/api/ticketflow/accounts"
GROUPS = "/api/ticketflow/skill-groups"
PASSWORD = "Garden-River-87!Cloud"
NEW_PASSWORD = "Forest-Lantern-23!Creek"

pytestmark = pytest.mark.django_db


def account_payload(password=PASSWORD, **overrides):
    return {
        "username": "new-employee",
        "name": "新员工",
        "email": "new-employee@example.com",
        "phone": "13800001234",
        "role": "requester",
        "password": password,
    } | overrides


def management_client(users, client_for):
    return client_for(users["admin"])


def test_create_edit_filter_and_metadata(users, client_for, settings):
    settings.SECURITY_USER_PASSWORD_ENCRYPTED_ENABLED = True
    api = management_client(users, client_for)
    payload = account_payload(AESCipherV2("new-employee").encrypt(PASSWORD.encode()).decode())
    response = api.post(ACCOUNTS, payload, format="json")
    assert response.status_code == 201, response.json()
    record = response.json()["data"]
    assert record == {
        "pk": record["pk"],
        "username": "new-employee",
        "name": "新员工",
        "email": "new-employee@example.com",
        "phone": "13800001234",
        "role": "requester",
        "skill_group": None,
        "skill_group_name": None,
        "is_active": True,
    }
    user = UserInfo.objects.get(pk=record["pk"])
    assert user.check_password(PASSWORD)
    assert user.date_password_updated is not None
    assert not user.is_superuser and not user.is_staff
    path = f"{ACCOUNTS}/{user.pk}"
    assert api.get(path).json()["data"] == record
    assert api.patch(path, {"name": "员工新名字", "is_active": False}, format="json").status_code == 200
    result = api.get(ACCOUNTS, {"q": "新名字", "role": "requester", "is_active": "false", "with_meta": "1"}).json()[
        "data"
    ]
    assert result["total"] == 1
    assert result["results"][0]["is_active"] is False
    assert api.patch(path, {"is_active": True}, format="json").json()["data"]["is_active"] is True
    columns = {field["key"]: field for field in result["search_columns"]}
    assert {key for key, field in columns.items() if field.get("table_show")} == {
        "username",
        "name",
        "phone",
        "email",
        "role",
        "skill_group_name",
        "is_active",
    }
    assert columns["password"]["input_type"] == "password"
    group = columns["skill_group"]
    assert group["input_type"] == "object_related_field"
    assert any(choice["value"] == str(users["agent"].dept_id) for choice in group["choices"])
    for path in (ACCOUNTS, GROUPS):
        assert api.get(f"{path}/search-columns").status_code == 200
        assert api.get(f"{path}/search-fields").status_code == 200


def test_management_rejects_non_business_admins_and_protects_platform_targets(users, client_for):
    api = management_client(users, client_for)
    superuser = UserInfo.objects.create_superuser(username="platform-root")
    platform_role, _ = UserRole.objects.get_or_create(code="platform-extra", defaults={"name": "平台角色"})
    role = UserRole.objects.get(code=REQUESTER_ROLE)
    mixed = UserInfo.objects.create_user(username="mixed-account")
    mixed.roles.add(role, platform_role)
    dept = DeptInfo.objects.create(code="platform-dept", name="平台部门", is_ticketflow_skill_group=True)
    dept.roles.add(platform_role)
    inherited = UserInfo.objects.create_user(username="inherited-account", dept=dept)
    inherited.roles.add(role)
    assert not {superuser.pk, mixed.pk, inherited.pk} & {
        account["pk"] for account in api.get(ACCOUNTS).json()["data"]["results"]
    }
    for user in (users["requester"], users["agent"], superuser):
        other_api = client_for(user)
        assert other_api.get(ACCOUNTS).status_code == 403
        assert other_api.get(f"{GROUPS}/category-routes").status_code == 403
    for user in (superuser, mixed, inherited):
        path = f"{ACCOUNTS}/{user.pk}"
        assert api.get(path).status_code == 404
        assert api.patch(path, {"name": "无法修改"}, format="json").status_code == 404
        assert api.post(f"{path}/reset-password", {"password": NEW_PASSWORD}, format="json").status_code == 404
    for payload in (
        account_payload(role="platform-extra"),
        account_payload(is_superuser=True),
        account_payload(roles=[str(platform_role.pk)]),
        account_payload(role="agent", skill_group=str(dept.pk)),
    ):
        assert api.post(ACCOUNTS, payload, format="json").status_code == 400
    path = f"{ACCOUNTS}/{users['admin'].pk}"
    assert api.patch(path, {"role": "requester"}, format="json").status_code == 403
    assert api.patch(path, {"is_active": False}, format="json").status_code == 403


@pytest.mark.parametrize("field", ["pk", "username", "nickname", "phone", "email", "dept", "is_active"])
def test_account_list_orders_by_supported_fields(users, client_for, field):
    requester = users["requester"]
    requester.is_active = False
    requester.dept = None
    requester.nickname = "A"
    requester.phone = "13800001234"
    requester.email = "a@example.com"
    requester.save(update_fields=["is_active", "dept", "nickname", "phone", "email"])
    accounts = UserInfo.objects.filter(pk__in=[user.pk for user in users.values()])
    api = management_client(users, client_for)
    for ordering in (field, f"-{field}"):
        response = api.get(ACCOUNTS, {"ordering": f"{ordering},pk"})
        assert response.status_code == 200, response.data
        assert [row["pk"] for row in response.data["data"]["results"]] == list(
            accounts.order_by(ordering, "pk").values_list("pk", flat=True)
        )


@pytest.mark.parametrize("ordering", ["role", "-role", "unknown"])
def test_account_list_ignores_unsupported_ordering(users, client_for, ordering):
    api = management_client(users, client_for)
    response = api.get(ACCOUNTS, {"ordering": ordering})
    assert response.status_code == 200, response.data
    assert response.data["data"] == api.get(ACCOUNTS).data["data"]


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "requester"}])
def test_technician_removal_releases_only_open_tickets(users, client_for, make_ticket, details, change):
    agent = users["agent"]
    unfinished, _ = create_ticket(users["requester"], str(uuid4()), details)
    closed = make_ticket(status=Status.CLOSED, assignee=agent)
    api = management_client(users, client_for)
    response = api.patch(f"{ACCOUNTS}/{agent.pk}", change, format="json")
    assert response.status_code == 200, response.json()
    if "role" in change:
        assert response.json()["data"]["skill_group"] is None
        assert agent.roles.get().code == REQUESTER_ROLE
    unfinished.refresh_from_db()
    closed.refresh_from_db()
    assert unfinished.status == Status.OPEN
    assert unfinished.assignee_id is None and unfinished.version == 2
    history = unfinished.assignments.get()
    assert history.assignee_id == agent.pk
    assert history.end_reason == TicketAssignment.EndReason.DEACTIVATED and history.ended_at is not None
    assert unfinished.logs.get(action="DEACTIVATED").operator_id == users["admin"].pk
    assert closed.assignee_id == agent.pk
    assert api.get("/api/tickets", {"assignment": "unassigned"}).json()["data"]["total"] == 1
    newly_created, _ = create_ticket(users["requester"], str(uuid4()), details)
    assert newly_created.assignee_id is None


@pytest.mark.parametrize("operation", ["reset", "deactivate", "change-role"])
def test_admin_account_changes_revoke_credentials_after_commit(
    users, client_for, settings, operation, django_capture_on_commit_callbacks
):
    settings.SECURITY_USER_PASSWORD_ENCRYPTED_ENABLED = False
    agent = users["agent"]
    session = UserSession.objects.create(creator=agent)
    password_updated = agent.date_password_updated
    refresh = ServerRefreshToken.for_user(agent)
    # Stable across subsecond clock skew in virtualized test runners.
    refresh["iat"] -= 60
    access = refresh.access_token
    access["iat"] = refresh["iat"]
    old_session = APIClient(HTTP_AUTHORIZATION=f"Bearer {access}", HTTP_USER_AGENT="pytest-agent")
    assert old_session.get("/api/tickets").status_code == 200
    path = f"{ACCOUNTS}/{agent.pk}"
    api = management_client(users, client_for)

    def change_account():
        if operation == "reset":
            return api.post(f"{path}/reset-password", {"password": NEW_PASSWORD}, format="json")
        change = {"is_active": False} if operation == "deactivate" else {"role": "requester"}
        return api.patch(path, change, format="json")

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            assert change_account().status_code == 200
            transaction.set_rollback(True)
    agent.refresh_from_db()
    assert agent.date_password_updated == password_updated
    assert old_session.get("/api/tickets").status_code == 200

    with django_capture_on_commit_callbacks(execute=True):
        started_at = timezone.now()
        response = change_account()
        assert response.status_code == 200, response.data
        session.refresh_from_db()
        assert session.status == UserSession.Status.ONLINE
        assert UserTokenRevokedCache(agent.pk).get_storage_cache() is None
    if operation == "reset":
        agent.refresh_from_db()
        assert agent.check_password(NEW_PASSWORD)
        assert agent.date_password_updated is not None and agent.date_password_updated >= started_at
    session.refresh_from_db()
    assert session.status == UserSession.Status.OFFLINE
    assert old_session.get("/api/tickets").status_code == 401
    assert APIClient().post("/api/identity/refresh", {"refresh": str(refresh)}, format="json").status_code == 401


def test_group_routes_and_deactivation_constraints(users, client_for, details):
    api = management_client(users, client_for)
    response = api.post(GROUPS, {"name": "网络支持", "description": "VPN 和内网"}, format="json")
    assert response.status_code == 201, response.json()
    group = response.json()["data"]
    pk = group["pk"]
    path = f"{GROUPS}/{pk}"
    assert group == {"pk": pk, "name": "网络支持", "description": "VPN 和内网", "is_active": True, "is_default": False}
    assert api.patch(path, {"name": "网络支持组"}, format="json").json()["data"]["name"] == "网络支持组"
    support = users["agent"].dept
    assert api.patch(f"{GROUPS}/{support.pk}", {"is_active": False}, format="json").status_code == 409
    routes_path = f"{GROUPS}/category-routes"
    routes = api.get(routes_path).json()["data"]
    assert {row["category"] for row in routes} == set(Category.values)
    route_path = f"{routes_path}/NETWORK"
    assert api.patch(route_path, {"skill_group": pk}, format="json").json()["data"] == {
        "category": "NETWORK",
        "label": "网络",
        "skill_group": pk,
        "skill_group_name": "网络支持组",
    }
    conflict = api.patch(path, {"is_active": False}, format="json")
    assert conflict.status_code == 409
    assert "工单分类" in conflict.json()["detail"]
    tech = UserInfo.objects.create_user(username="network-tech", dept_id=pk)
    tech.roles.add(UserRole.objects.get(code=AGENT_ROLE))
    network_ticket, _ = create_ticket(users["requester"], str(uuid4()), details)
    assert str(network_ticket.department_id) == pk and network_ticket.assignee_id == tech.pk
    assert api.patch(route_path, {"skill_group": None}, format="json").json()["data"]["skill_group"] is None
    fallback_ticket, _ = create_ticket(users["requester"], str(uuid4()), details)
    assert fallback_ticket.department_id == support.pk and fallback_ticket.assignee_id == users["agent"].pk
    conflict = api.patch(path, {"is_active": False}, format="json")
    assert conflict.status_code == 409
    assert "在职技术员" in conflict.json()["detail"]
    tech.date_expired = timezone.now()
    tech.save(update_fields=["date_expired"])
    assert api.patch(path, {"is_active": False}, format="json").json()["data"]["is_active"] is False
    assert api.patch(route_path, {"skill_group": pk}, format="json").status_code == 400
    assert api.patch(path, {"is_active": True}, format="json").status_code == 200
    network_ticket.refresh_from_db()
    assert str(network_ticket.department_id) == pk


def test_password_policy_and_operation_log(users, client_for, settings):
    settings.API_LOG_ENABLE = True
    settings.API_LOG_METHODS = ["POST", "PATCH"]
    settings.SECURITY_USER_PASSWORD_ENCRYPTED_ENABLED = False
    api = management_client(users, client_for)
    assert api.post(ACCOUNTS, account_payload("x"), format="json").status_code == 400
    assert api.post(ACCOUNTS, account_payload(role="agent"), format="json").status_code == 400
    account = api.post(ACCOUNTS, account_payload(), format="json")
    assert account.status_code == 201, account.json()
    path = f"{ACCOUNTS}/{account.json()['data']['pk']}/reset-password"
    assert api.post(path, {"password": "x"}, format="json").status_code == 400
    assert api.post(path, {"password": NEW_PASSWORD}, format="json").status_code == 200
    assert api.post(GROUPS, {"name": "外设支持"}, format="json").status_code == 201
    logs = OperationLog.objects.filter(creator=users["admin"], status_code=1000, path__in=[ACCOUNTS, GROUPS, path])
    assert set(logs.values_list("path", flat=True)) == {ACCOUNTS, GROUPS, path}
    for log in logs:
        assert PASSWORD not in str(log.body) and NEW_PASSWORD not in str(log.body)
        if log.path != GROUPS:
            assert set(json.loads(log.body)["password"]) == {"*"}


def test_upgrade_imports_configured_routes_without_overwriting_saved_routes(users, settings):
    migration = import_module("tickets.migrations.0007_import_category_routes")
    apps = MigrationExecutor(connection).loader.project_state([("tickets", "0007_import_category_routes")]).apps
    first = DeptInfo.objects.create(code="legacy-network", name="旧网络组")
    second = DeptInfo.objects.create(code="updated-network", name="新网络组")
    settings.TICKETFLOW_CATEGORY_DEPARTMENTS = {"NETWORK": str(first.pk), "OTHER": "invalid-id"}

    with connection.schema_editor(atomic=False) as editor:
        migration.import_category_routes(apps, editor)
        first.refresh_from_db()
        assert first.is_ticketflow_skill_group
        route = CategoryRoute.objects.get()
        assert route.category == Category.NETWORK and route.skill_group_id == first.pk
        route.skill_group = second
        route.save(update_fields=["skill_group"])
        migration.import_category_routes(apps, editor)

    route.refresh_from_db()
    assert route.skill_group_id == second.pk
