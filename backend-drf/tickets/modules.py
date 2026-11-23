from common.core.modules.specs import STANDARD, ModuleSpec

MODULES = (
    ModuleSpec(
        "ticketflow_tickets",
        "工单",
        STANDARD,
        depends=("core_auth", "core_rbac", "core_file"),
        menus=(
            "TicketFlowTickets",
            "TicketFlowMyRatings",
            "TicketFlowRatingStats",
            "TicketFlowAccounts",
            "TicketFlowSkillGroups",
        ),
        permissions=("api/tickets", "api/ticket-ratings", "api/ticketflow/accounts", "api/ticketflow/skill-groups"),
        routes=(
            r"^/api/tickets(?:/|$)",
            r"^/api/ticket-ratings(?:/|$)",
            r"^/api/ticketflow/accounts(?:/|$)",
            r"^/api/ticketflow/skill-groups(?:/|$)",
        ),
    ),
)
