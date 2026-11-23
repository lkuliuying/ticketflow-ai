"""Seed the opt-in deployment demo through the ticket and knowledge services."""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import NamedTuple
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from identity.models import DeptInfo, UserInfo, UserRole
from knowledge.models import ArticleStatus
from knowledge.services import create_article
from tickets.assignment import dispatch
from tickets.cache import invalidate_dashboard
from tickets.models import Category, Priority, Status, Ticket, Visibility
from tickets.policy import ADMIN_ROLE, AGENT_ROLE, REQUESTER_ROLE, TicketAccess
from tickets.services import add_comment, create_ticket, transition

REQUESTER = "tf_requester"
AGENT = "tf_agent"
NETWORK_AGENT = "tf_agent_other"
ADMIN = "tf_admin"
USERNAMES = (REQUESTER, AGENT, NETWORK_AGENT, ADMIN)


class Sample(NamedTuple):
    title: str
    description: str
    category: str
    priority: str
    status: str
    age_minutes: int
    with_comments: bool = True
    requester: str = REQUESTER


SAMPLES = (
    Sample(
        "门户密码重置邮件未收到",
        "已提交两次密码重置，均未收到邮件。",
        str(Category.ACCOUNT),
        str(Priority.P2),
        str(Status.OPEN),
        19,
        False,
    ),
    Sample(
        "园区 VPN 无法连接",
        "办公网和热点都显示 VPN 握手超时。",
        str(Category.NETWORK),
        str(Priority.P0),
        str(Status.OPEN),
        102,
        False,
    ),
    Sample(
        "财务报表权限失效",
        "组织权限同步后无法打开月度财务报表。",
        str(Category.ACCESS),
        str(Priority.P1),
        str(Status.IN_PROGRESS),
        25,
    ),
    Sample(
        "分公司到总部网络丢包",
        "线路波动超过两小时，视频会议频繁中断。",
        str(Category.NETWORK),
        str(Priority.P0),
        str(Status.IN_PROGRESS),
        180,
    ),
    Sample(
        "工单通知未显示",
        "通知中心显示空列表，重新登录仍未恢复。",
        str(Category.SERVICE),
        str(Priority.P2),
        str(Status.PENDING_VERIFY),
        40,
    ),
    Sample(
        "无线访客认证页面循环跳转",
        "访客手机连接访客网后重复跳转认证页面。",
        str(Category.NETWORK),
        str(Priority.P1),
        str(Status.PENDING_VERIFY),
        60,
    ),
    Sample(
        "账户切换后首页仍显示旧部门",
        "所属部门已更新，首页摘要仍显示旧部门。",
        str(Category.ACCOUNT),
        str(Priority.P1),
        str(Status.CLOSED),
        55,
    ),
    Sample(
        "办公电脑 DNS 解析超时",
        "切换办公网后内网域名首次解析失败。",
        str(Category.NETWORK),
        str(Priority.P2),
        str(Status.CLOSED),
        80,
    ),
    Sample(
        "附件预览提示格式不支持",
        "上传 PDF 后网页预览失败，下载可以打开。",
        str(Category.SERVICE),
        str(Priority.P3),
        str(Status.CLOSED),
        65,
    ),
    Sample(
        "审批列表刷新后筛选重置",
        "验收后仍可在其他浏览器复现，需重新处理。",
        str(Category.OTHER),
        str(Priority.P2),
        str(Status.REOPENED),
        45,
    ),
    Sample(
        "园区交换机端口不稳定",
        "连接测试终端后端口时断时续。",
        str(Category.NETWORK),
        str(Priority.P3),
        str(Status.IN_PROGRESS),
        31,
        False,
        ADMIN,
    ),
    Sample(
        "单点登录回调服务不可用",
        "从内部门户跳转到业务系统时回调失败。",
        str(Category.SERVICE),
        str(Priority.P0),
        str(Status.OPEN),
        240,
        False,
        ADMIN,
    ),
)


def ensure_seed_owner() -> None:
    """Reserve the audit user referenced by upstream seeds on a fresh database."""
    if not UserInfo.objects.exists():
        with transaction.atomic():
            owner = UserInfo.objects.create_user(username="ticketflow_seed_owner", is_active=False)
            if owner.pk != 1:
                raise CommandError("The base seeds require an audit user with primary key 1")


def create_accounts(passwords: dict[str, str], support: DeptInfo, network: DeptInfo) -> dict[str, UserInfo]:
    accounts = {}
    for username, nickname, role, department in (
        (REQUESTER, "演示员工", REQUESTER_ROLE, None),
        (AGENT, "工单支持技术员", AGENT_ROLE, support),
        (NETWORK_AGENT, "网络支持技术员", AGENT_ROLE, network),
        (ADMIN, "演示管理员", ADMIN_ROLE, support),
    ):
        user = UserInfo.objects.create_user(
            username=username,
            password=passwords[username],
            nickname=nickname,
            dept=department,
            date_password_updated=timezone.now(),
        )
        user.roles.add(UserRole.objects.get(code=role))
        accounts[username] = user
    return accounts


def seed_ticket(sample: Sample, accounts: dict[str, UserInfo], now: datetime) -> Ticket:
    requester = accounts[sample.requester]
    requester_access = TicketAccess.for_user(requester)
    tickets = Ticket.objects.all()
    opened = now - timedelta(minutes=sample.age_minutes)
    with patch.object(timezone, "now", return_value=opened):
        ticket, _ = create_ticket(
            requester,
            f"ticketflow-demo:{sample.title}",
            {
                "title": sample.title,
                "description": sample.description,
                "category": sample.category,
                "priority": sample.priority,
            },
        )
    handler = ticket.assignee or accounts[ADMIN]
    handler_access = TicketAccess.for_user(handler)
    if sample.with_comments:
        with patch.object(timezone, "now", return_value=opened + timedelta(seconds=90)):
            scoped = handler_access.scope(tickets)
            add_comment(
                scoped,
                ticket.pk,
                handler,
                handler_access,
                "已接收问题，正在核对复现条件。",
                Visibility.PUBLIC,
            )
            add_comment(
                scoped,
                ticket.pk,
                handler,
                handler_access,
                "先核对设备和服务端日志。",
                Visibility.INTERNAL,
            )
    if sample.status == Status.OPEN:
        return ticket
    states = (Status.IN_PROGRESS, Status.PENDING_VERIFY, Status.CLOSED, Status.REOPENED)
    for offset, state in enumerate(states, start=2):
        actor, access = (
            (requester, requester_access) if state in (Status.CLOSED, Status.REOPENED) else (handler, handler_access)
        )
        with patch.object(timezone, "now", return_value=opened + timedelta(minutes=offset)):
            ticket = transition(
                access.scope(tickets),
                ticket.pk,
                actor,
                access,
                ticket.version,
                state,
                "演示样例流转",
            )
        if state == sample.status:
            break
    return ticket


def seed_articles(accounts: dict[str, UserInfo], tickets: dict[str, Ticket]) -> None:
    for author, label, title, body, source in (
        (
            ADMIN,
            "VPN",
            "VPN 连接失败排查指南",
            "先核对网络连通性、客户端版本和系统时间。",
            None,
        ),
        (
            ADMIN,
            "DNS",
            "办公网络 DNS 超时排查",
            "检查内网 DNS 配置，判断影响范围。",
            "办公电脑 DNS 解析超时",
        ),
        (
            AGENT,
            "附件",
            "PDF 附件预览故障记录",
            "附件可下载。待核对预览渲染器日志。",
            "附件预览提示格式不支持",
        ),
    ):
        ticket = tickets[source] if source else None
        user = accounts[author] if author == ADMIN or ticket is None else ticket.assignee or accounts[ADMIN]
        article = create_article(
            user,
            TicketAccess.for_user(user),
            {
                "title": title,
                "body_markdown": body,
                "category": ticket.category if ticket else Category.NETWORK,
                "tags": [label],
            },
            ticket.pk if ticket else None,
        )
        if author == ADMIN:
            article.status = ArticleStatus.PUBLISHED
            article.save(update_fields=["status", "updated_time"])


def dispatch_existing_samples(accounts: dict[str, UserInfo]) -> None:
    for sample in SAMPLES:
        ticket = (
            Ticket.objects.select_for_update(of=("self",))
            .filter(
                title=sample.title,
                description=sample.description,
                submitter=accounts[sample.requester],
                assignee__isnull=True,
                assignments__isnull=True,
            )
            .exclude(status=Status.CLOSED)
            .first()
        )
        if ticket is not None:
            dispatch(ticket)
            if ticket.assignee_id is not None:
                ticket.save(update_fields=["assignee"])
                transaction.on_commit(invalidate_dashboard, robust=True)


@transaction.atomic
def seed(passwords: dict[str, str]) -> bool:
    support = DeptInfo.objects.select_for_update().get(code="ticketflow_support")
    existing = {user.username: user for user in UserInfo.objects.filter(username__in=USERNAMES)}
    if existing:
        if set(existing) == set(USERNAMES) and all(
            user.check_password(passwords[name]) for name, user in existing.items()
        ):
            dispatch_existing_samples(existing)
            return False
        raise CommandError(
            "Demo usernames already exist with different credentials; restore the original accounts file"
        )

    network = DeptInfo.objects.create(code="ticketflow_demo_network", name="网络支持组")
    accounts = create_accounts(passwords, support, network)
    routing = {
        **settings.TICKETFLOW_CATEGORY_DEPARTMENTS,
        Category.NETWORK: str(network.pk),
    }
    now = timezone.now()
    with override_settings(TICKETFLOW_CATEGORY_DEPARTMENTS=routing):
        tickets = {sample.title: seed_ticket(sample, accounts, now) for sample in SAMPLES}
    seed_articles(accounts, tickets)
    return True


def main() -> None:
    if os.environ.get("TICKETFLOW_DEMO", "").lower() != "true":
        raise CommandError("Set TICKETFLOW_DEMO=true in deploy/.env and recreate the stack before seeding")
    try:
        passwords = json.load(sys.stdin)
    except ValueError:
        raise CommandError("Invalid demo accounts file") from None
    if (
        not isinstance(passwords, dict)
        or set(passwords) != set(USERNAMES)
        or not all(isinstance(password, str) and len(password) >= 24 for password in passwords.values())
    ):
        raise CommandError("Invalid demo accounts file")
    if seed(passwords):
        print(f"Created {len(USERNAMES)} demo users, {len(SAMPLES)} tickets and 3 articles")
    else:
        print("Demo data already initialized")
