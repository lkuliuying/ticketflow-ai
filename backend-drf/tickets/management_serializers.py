from collections.abc import Mapping
from typing import Any

from django.contrib.auth.validators import UnicodeUsernameValidator
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from common.core.fields import PasswordField
from common.core.serializers import BaseModelSerializer, BasePrimaryKeyRelatedField
from identity.models import DeptInfo, UserInfo
from tickets.accounts import ROLE_CHOICES, ROLE_NAMES
from tickets.models import Category
from tickets.policy import AGENT_ROLE
from tickets.skill_groups import skill_groups


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, Mapping):
            writable = {name for name, field in self.fields.items() if not field.read_only}
            unknown = sorted(set(data) - writable)
            if unknown:
                raise serializers.ValidationError({key: "此字段不可写" for key in unknown})
        return super().to_internal_value(data)


class BusinessRoleField(serializers.ChoiceField):
    def get_attribute(self, instance: UserInfo) -> str:
        return ROLE_NAMES[next(iter(instance.roles.all())).code]


@extend_schema_field({"type": "string", "format": "uuid"})
class AccountSkillGroupField(BasePrimaryKeyRelatedField):
    def get_queryset(self) -> Any:
        return skill_groups()

    def get_attribute(self, instance: UserInfo) -> Any:
        if next(iter(instance.roles.all())).code != AGENT_ROLE:
            return None
        return super().get_attribute(instance)

    def to_representation(self, instance: DeptInfo) -> str | dict[str, str]:
        pk = str(instance.pk)
        if getattr(self, "is_column", False):
            return {"pk": pk, "label": instance.name}
        return pk

    def to_internal_value(self, data: Any) -> DeptInfo:
        return super().to_internal_value(serializers.UUIDField().run_validation(data))


class AccountSerializer(StrictInput, BaseModelSerializer):
    # The dedicated business role has access to this bounded field set.
    ignore_field_permission = True

    pk = serializers.IntegerField(read_only=True, label="编号")
    username = serializers.CharField(max_length=150, validators=[UnicodeUsernameValidator()], label="用户名")
    name = serializers.CharField(source="nickname", max_length=150, label="姓名")
    phone = serializers.CharField(max_length=16, allow_blank=True, required=False, label="手机")
    email = serializers.EmailField(max_length=254, allow_blank=True, required=False, label="邮箱")
    role = BusinessRoleField(choices=ROLE_CHOICES, label="角色")
    skill_group = AccountSkillGroupField(
        source="dept",
        allow_null=True,
        required=False,
        label="技能组",
    )
    skill_group_name = serializers.SerializerMethodField(label="技能组名称")
    is_active = serializers.BooleanField(default=True, label="启用")

    @staticmethod
    def validate_username(value: str) -> str:
        return UserInfo.normalize_username(value)

    @staticmethod
    def validate_email(value: str) -> str:
        return UserInfo.objects.normalize_email(value)

    @staticmethod
    def get_skill_group_name(instance: UserInfo) -> str | None:
        if next(iter(instance.roles.all())).code == AGENT_ROLE and instance.dept_id is not None:
            return instance.dept.name
        return None

    class Meta:
        model = UserInfo
        table_fields = ("username", "name", "phone", "email", "role", "skill_group_name", "is_active")
        fields: tuple[str, ...] = ("pk", *table_fields, "skill_group")
        validators: list[Any] = []


class AccountPasswordSerializer(StrictInput):
    password = PasswordField(max_length=512, trim_whitespace=False, write_only=True, label="密码")


class AccountCreateSerializer(AccountSerializer):
    password = PasswordField(max_length=512, trim_whitespace=False, write_only=True, label="初始密码")

    class Meta(AccountSerializer.Meta):
        fields = (*AccountSerializer.Meta.fields, "password")


class SkillGroupSerializer(StrictInput, BaseModelSerializer):
    ignore_field_permission = True

    pk = serializers.UUIDField(read_only=True, label="编号")
    name = serializers.CharField(max_length=128, label="名称")
    description = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        allow_null=True,
        label="描述",
    )
    is_active = serializers.BooleanField(default=True, label="启用")
    is_default = serializers.BooleanField(read_only=True, label="默认技能组")

    class Meta:
        model = DeptInfo
        table_fields = ("name", "description", "is_active", "is_default")
        fields = ("pk", *table_fields)


class CategoryRouteSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=Category.choices)
    label = serializers.CharField()
    skill_group = serializers.UUIDField(allow_null=True)
    skill_group_name = serializers.CharField(allow_null=True)


class CategoryRouteInputSerializer(StrictInput):
    skill_group = serializers.UUIDField(allow_null=True)
