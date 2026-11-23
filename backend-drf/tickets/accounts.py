from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from identity.models import DeptInfo, UserInfo, UserRole
from identity.serializers.user import ensure_local_password_changeable
from identity.serializers.userinfo import decrypt_submitted_password
from identity.utils.session import revoke_user_credentials
from settings.services import (
    check_history_password,
    check_leak_password,
    check_password_rules,
    record_password_hash,
)
from tickets.policy import ADMIN_ROLE, AGENT_ROLE, REQUESTER_ROLE
from tickets.services import release_assigned_tickets
from tickets.skill_groups import skill_groups

ROLE_CODES = {"requester": REQUESTER_ROLE, "agent": AGENT_ROLE, "admin": ADMIN_ROLE}
ROLE_NAMES = {code: name for name, code in ROLE_CODES.items()}
ROLE_CHOICES = (("requester", "普通员工"), ("agent", "技术员"), ("admin", "管理员"))


def business_accounts() -> QuerySet[UserInfo]:
    # A platform account with additional roles must not be reachable through business password reset.
    direct_roles = UserRole.objects.filter(userinfo=OuterRef("pk"))
    inherited_roles = UserRole.objects.filter(deptinfo__pk=OuterRef("dept_id"))
    role_filter = Q()
    for code in ROLE_CODES.values():
        role_filter |= (
            Q(Exists(direct_roles.filter(code=code, is_active=True)))
            & ~Q(Exists(direct_roles.exclude(code=code)))
            & ~Q(Exists(inherited_roles.exclude(code=code)))
        )
    return UserInfo.objects.filter(role_filter, is_superuser=False, is_staff=False).order_by("username", "pk")


def lock_account(pk: int) -> UserInfo:
    account = UserInfo.objects.select_for_update(no_key=True).filter(pk=pk, pk__in=business_accounts()).first()
    if account is None:
        raise NotFound("业务账号不存在")
    return account


def _role(name: str) -> UserRole:
    role = UserRole.objects.filter(code=ROLE_CODES[name], is_active=True).first()
    if role is None:
        raise ValidationError({"role": "该业务角色当前不可用"})
    return role


def _group_for(user: UserInfo, role: UserRole, values: dict[str, Any]) -> DeptInfo | None:
    previous = user.dept_id
    if "dept" in values:
        requested_group = values.pop("dept")
        group_id = requested_group.pk if requested_group is not None else None
    else:
        group_id = previous if role.code == AGENT_ROLE else None
    # Group locks serialize routing, eligibility changes and dispatch before any ticket rows are locked.
    groups = {
        group.pk: group
        for group in DeptInfo.objects.select_for_update(no_key=True).filter(pk__in={previous, group_id}).order_by("pk")
    }
    if role.code != AGENT_ROLE:
        if group_id is not None:
            raise ValidationError({"skill_group": "只有技术员可以设置技能组"})
        return None
    group = groups.get(group_id)
    keep_disabled = group_id == previous and not values.get("is_active", user.is_active)
    if (
        group is None
        or (not group.is_active and not keep_disabled)
        or not skill_groups().filter(pk=group.pk).exists()
        or group.roles.exclude(code=AGENT_ROLE).exists()
    ):
        raise ValidationError({"skill_group": "请选择可分配给技术员的启用技能组"})
    return group


def _save_account(user: UserInfo, fields: list[str]) -> None:
    try:
        with transaction.atomic():
            user.save(update_fields=fields if user.pk else None)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", "") or ""
        field = {
            "uniq_userinfo_email_active": "email",
            "uniq_userinfo_phone_active": "phone",
        }.get(constraint)
        if constraint.endswith("_username_key"):
            field = "username"
        if field is None:
            raise
        raise ValidationError({field: "该值已被使用"}) from exc


def _set_password(user: UserInfo, submitted: str, *, reset: bool = False) -> None:
    password = decrypt_submitted_password(user, submitted)
    if not check_password_rules(password):
        raise ValidationError({"password": _("Password does not match security rules")})
    if check_leak_password(password):
        raise ValidationError({"password": _("Password has been leaked, please change to another one")})
    if reset and check_history_password(user, password):
        raise ValidationError(
            {
                "password": _("Password cannot reuse the recent %(count)s passwords")
                % {"count": settings.SECURITY_PASSWORD_HISTORY_COUNT}
            }
        )
    user.set_password(password)


def save_account(user: UserInfo, actor: UserInfo, values: dict[str, Any]) -> UserInfo:
    previous_role = user.roles.get(is_active=True) if user.pk else None
    role_name = values.pop("role", None)
    role = _role(role_name) if role_name else previous_role
    if role is None:
        raise ValidationError({"role": "请选择业务角色"})
    role_changed = previous_role != role
    deactivated = user.is_active and values.get("is_active") is False
    if user.pk == actor.pk and (role_changed or deactivated):
        raise PermissionDenied("不能更改自己的角色或停用自己的账号")
    if role_changed and role.code == AGENT_ROLE and "dept" not in values:
        raise ValidationError({"skill_group": "技术员必须设置技能组"})
    user.dept = _group_for(user, role, values)
    password = values.pop("password", None)
    for field, value in values.items():
        setattr(user, field, value)
    user.modifier = actor
    if previous_role is None:
        if password is None:
            raise ValidationError({"password": "请设置初始密码"})
        user.creator = actor
        _set_password(user, password)
    _save_account(user, [*values, "dept", "modifier", "updated_time"])
    if role_changed:
        user.roles.set([role])
    if password is not None:
        record_password_hash(user, user.password)
    if previous_role is not None and previous_role.code == AGENT_ROLE and (deactivated or role_changed):
        note = "技术员账号已停用" if deactivated else "账号已变更为非技术员"
        release_assigned_tickets(user, actor, note)
    if previous_role is not None and (deactivated or role_changed):
        revoke_user_credentials(user.pk, operator=actor)
    return user


def reset_account_password(user: UserInfo, actor: UserInfo, password: str) -> None:
    ensure_local_password_changeable(user)
    _set_password(user, password, reset=True)
    user.modifier = actor
    user.save(update_fields=["password", "modifier", "updated_time"])
    record_password_hash(user, user.password)
    revoke_user_credentials(user.pk, operator=actor)
