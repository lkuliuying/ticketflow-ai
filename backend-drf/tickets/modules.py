from common.core.modules.specs import STANDARD, ModuleSpec

MODULES = (
    ModuleSpec(
        "ticketflow_tickets",
        "工单",
        STANDARD,
        depends=("core_auth", "core_rbac", "core_file"),
        menus=("TicketFlowTickets", "TicketFlowMyRatings", "TicketFlowRatingStats"),
        permissions=("api/tickets", "api/ticket-ratings"),
        routes=(r"^/api/tickets(?:/|$)", r"^/api/ticket-ratings(?:/|$)"),
    ),
)
