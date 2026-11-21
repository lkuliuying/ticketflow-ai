import pytest

from identity.models import DeptInfo, UserInfo, UserRole
from tickets.models import Category, Priority
from tickets.policy import AGENT_ROLE
from tickets.services import NewTicket


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
