"""Protect editable brand fields when built-in fixtures are reloaded."""

from typing import Any

from django.apps import apps
from django.db import connections


def _stored_field(label: str, row: dict[str, Any], field: str, using: str) -> Any:
    queryset = apps.get_model(label)._default_manager.using(using)
    if connections[using].in_atomic_block:
        queryset = queryset.select_for_update()
    return queryset.filter(pk=row["pk"]).values_list(field, flat=True).first()


def preserve_branding(rows_by_model: dict[str, list[Any]], *, using: str) -> bool:
    """Copy existing brand fields into fixtures for the same seeded records."""
    changed = False
    for row in rows_by_model.get("system.systemconfig", []):
        fields = row["fields"]
        seed_value = fields.get("value")
        if fields.get("key") != "WEB_SITE_CONFIG" or not isinstance(seed_value, dict) or "Title" not in seed_value:
            continue
        value = _stored_field("system.systemconfig", row, "value", using)
        if isinstance(value, dict) and "Title" in value and value["Title"] != seed_value["Title"]:
            seed_value["Title"] = value["Title"]
            changed = True

    for row in rows_by_model.get("identity.deptinfo", []):
        fields = row["fields"]
        if fields.get("code") != "xadmin" or fields.get("parent") is not None:
            continue
        name = _stored_field("identity.deptinfo", row, "name", using)
        if name is not None and name != fields.get("name"):
            fields["name"] = name
            changed = True

    return changed
