from common.core.modules.specs import STANDARD, ModuleSpec

MODULES = (
    ModuleSpec(
        "ticketflow_tickets",
        "工单",
        STANDARD,
        depends=("core_auth", "core_rbac", "core_file"),
        menus=("TicketFlowTickets",),
        permissions=("api/tickets",),
        routes=(r"^/api/tickets(?:/|$)",),
    ),
)
