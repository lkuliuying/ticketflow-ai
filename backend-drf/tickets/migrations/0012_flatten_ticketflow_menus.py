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


def flatten_ticketflow_menus(apps: Any, schema_editor: Any) -> None:
    menu_model = apps.get_model("system", "Menu")
    meta_model = apps.get_model("system", "MenuMeta")
    for name, rank in FLATTENED_RANKS.items():
        menu_model.objects.filter(name=name).update(parent=None, rank=rank)
    menu_model.objects.filter(pk=OLD_PARENT_PK).delete()
    meta_model.objects.filter(pk=OLD_META_PK).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0011_migrate_public_comments_to_chat"),
        ("system", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(flatten_ticketflow_menus, migrations.RunPython.noop),
    ]
