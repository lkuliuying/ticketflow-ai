from common.core.modules.specs import STANDARD, ModuleSpec

MODULES = (
    ModuleSpec(
        "ticketflow_knowledge",
        "工单知识库",
        STANDARD,
        depends=("ticketflow_tickets",),
        menus=("TicketFlowKnowledge",),
        routes=(r"^/api/knowledge/", r"^/api/tickets/[^/]+/ai-context$"),
    ),
)
