from typing import Any

from django.db import migrations

OLD_PARENT_PK = "d2431bc0-217a-49eb-a6fa-000000000090"
OLD_META_PK = "d2431bc0-217a-49eb-a6fa-000000000091"
FLATTENED_RANKS = {
    "TicketFlowTickets": 30,
    "TicketFlowKnowledge": 31,
    "TicketFlowAssistant": 32,
    "TicketFlowMyRatings": 33,
    "TicketFlowRatingStats": 34,
    "TicketFlowAccounts": 35,
    "TicketFlowSkillGroups": 36,
    "TicketFlowAssistantFeedback": 37,
}
OLD_PAGE_ORDER = (
    "TicketFlowTickets",
    "TicketFlowKnowledge",
    "TicketFlowMyRatings",
    "TicketFlowRatingStats",
    "TicketFlowAccounts",
    "TicketFlowSkillGroups",
    "TicketFlowAssistant",
    "TicketFlowAssistantFeedback",
)


def flatten_ticketflow_menus(apps: Any, schema_editor: Any) -> None:
    alias = schema_editor.connection.alias
    menus = apps.get_model("system", "Menu")._base_manager.using(alias)
    metas = apps.get_model("system", "MenuMeta").objects.using(alias)
    for name, rank in FLATTENED_RANKS.items():
        menus.filter(name=name, deleted_at__isnull=True).update(parent=None, rank=rank)
    menus.filter(pk=OLD_PARENT_PK).delete()
    metas.filter(pk=OLD_META_PK).delete()


def restore_ticketflow_menus(apps: Any, schema_editor: Any) -> None:
    alias = schema_editor.connection.alias
    menus = apps.get_model("system", "Menu")._base_manager.using(alias)
    metas = apps.get_model("system", "MenuMeta").objects.using(alias)
    roles = apps.get_model("identity", "UserRole")._base_manager.using(alias)
    pages = menus.filter(name__in=OLD_PAGE_ORDER, deleted_at__isnull=True)
    if not pages.exists():
        return
    metas.get_or_create(
        pk=OLD_META_PK, defaults={"title": "menus.ticketflow", "icon": "ep:tickets", "is_show_menu": True}
    )
    parent, _ = menus.get_or_create(
        pk=OLD_PARENT_PK,
        defaults={
            "name": "TicketFlow",
            "path": "/ticketflow",
            "component": "",
            "menu_type": 0,
            "rank": 30,
            "meta_id": OLD_META_PK,
            "method": "",
        },
    )
    for rank, name in enumerate(OLD_PAGE_ORDER, start=1):
        pages.filter(name=name).update(parent_id=parent.pk, rank=rank)
    # Use the existing page grants to preserve which roles see the directory on downgrade.
    for role in roles.filter(menu__in=pages).distinct():
        role.menu.add(parent)


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0011_migrate_public_comments_to_chat"),
        ("system", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(flatten_ticketflow_menus, restore_ticketflow_menus),
    ]
