from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from rest_framework.exceptions import APIException, ValidationError

from identity.models import DeptInfo, UserInfo
from tickets.models import CategoryRoute
from tickets.policy import assignment_candidates

DEFAULT_GROUP_CODE = "ticketflow_support"


class SkillGroupConflict(APIException):
    status_code = 409
    default_detail = "技能组仍在使用"


def default_group() -> Q:
    configured = settings.TICKETFLOW_DEFAULT_DEPARTMENT
    return Q(pk=configured) if configured else Q(code=DEFAULT_GROUP_CODE)


def skill_groups() -> QuerySet[DeptInfo]:
    return DeptInfo.objects.filter(
        Q(is_ticketflow_skill_group=True) | Q(code=DEFAULT_GROUP_CODE) | default_group()
    ).order_by("name", "pk")


def destination(category: str) -> DeptInfo:
    active = DeptInfo.objects.select_for_update(no_key=True).filter(is_active=True)
    routed = CategoryRoute.objects.filter(category=category).values("skill_group_id")
    group = active.filter(pk__in=routed).first() or active.filter(default_group()).first()
    if group is None:
        raise ValidationError({"department": "请配置可用的工单支持技能组"})
    return group


def create_skill_group(actor: UserInfo, values: dict) -> DeptInfo:
    return DeptInfo.objects.create(
        code=f"ticketflow_{uuid4().hex}", is_ticketflow_skill_group=True, creator=actor, modifier=actor, **values
    )


def update_skill_group(group: DeptInfo, actor: UserInfo, values: dict) -> DeptInfo:
    if values.get("is_active") is False and group.is_active:
        if skill_groups().filter(default_group(), pk=group.pk).exists():
            raise SkillGroupConflict("默认技能组不能停用")
        if assignment_candidates().filter(dept=group).exists():
            raise SkillGroupConflict("技能组仍有在职技术员")
        if group.ticket_routes.exists():
            raise SkillGroupConflict("技能组仍被工单分类使用")
    for field, value in values.items():
        setattr(group, field, value)
    group.modifier = actor
    group.save(update_fields=[*values, "modifier", "updated_time"])
    return group


@transaction.atomic
def set_category_route(category: str, group_id: UUID | None) -> None:
    if group_id is None:
        CategoryRoute.objects.filter(category=category).delete()
        return
    group = skill_groups().select_for_update(no_key=True).filter(pk=group_id, is_active=True).first()
    if group is None:
        raise ValidationError({"skill_group": "请选择启用的技能组"})
    CategoryRoute.objects.update_or_create(category=category, defaults={"skill_group": group})
