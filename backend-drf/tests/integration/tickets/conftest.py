from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from identity.models import DeptInfo, UserInfo, UserRole
from tickets.models import Category, Priority, Ticket
from tickets.policy import ADMIN_ROLE, AGENT_ROLE, REQUESTER_ROLE
from tickets.services import NewTicket


@pytest.fixture(scope="module")
def seed_apps() -> str:
    # 工单和知识库沿用正式菜单与字段白名单，任务中心提供导出记录的下载授权。
    # 其余应用提供平台数据权限引用的菜单，以及身份、设置和任务中心引用的菜单和字段。
    return "tickets,knowledge,task,settings,captcha,file,notifications,audit"


@pytest.fixture
def support() -> DeptInfo:
    return DeptInfo.objects.create(code="ticketflow_support", name="工单支持")


@pytest.fixture
def requester() -> UserInfo:
    return UserInfo.objects.create_user(username="requester")


@pytest.fixture
def agent(support: DeptInfo) -> UserInfo:
    role, _ = UserRole.objects.get_or_create(code=AGENT_ROLE, defaults={"name": "工单处理人"})
    user = UserInfo.objects.create_user(username="support", dept=support)
    user.roles.add(role)
    return user


@pytest.fixture
def details() -> NewTicket:
    return {
        "title": "网络连接错误",
        "description": "VPN 连接失败",
        "category": Category.NETWORK,
        "priority": Priority.P1,
    }


@pytest.fixture
def users(seeded_module, db) -> dict[str, UserInfo]:
    support_dept = DeptInfo.objects.get(code="ticketflow_support")
    result = {}
    for name, role in (("requester", REQUESTER_ROLE), ("agent", AGENT_ROLE), ("admin", ADMIN_ROLE)):
        user = UserInfo.objects.create_user(username=f"viewer-{name}", dept=support_dept)
        user.roles.add(UserRole.objects.get(code=role))
        result[name] = user
    return result


@pytest.fixture
def client_for(settings):
    def authenticate(user: UserInfo) -> APIClient:
        client = APIClient(
            HTTP_USER_AGENT="pytest-agent", HTTP_X_INTERNAL_TOKEN=settings.TICKETFLOW_INTERNAL_API_SECRET
        )
        client.force_authenticate(user=user)
        return client

    return authenticate


@pytest.fixture
def make_ticket(users, details):
    def create(submitter=None, **overrides):
        data = {
            **details,
            "number": f"TF-{uuid4().hex.upper()}",
            "submitter": submitter or users["requester"],
            "department": users["agent"].dept,
            "sla_due_at": timezone.now() + timedelta(hours=8),
        }
        return Ticket.objects.create(**(data | overrides))

    return create
