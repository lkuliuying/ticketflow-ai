from uuid import NAMESPACE_URL, uuid5

TICKET_COUNT = 5000
AGENT_COUNT = 32
TITLE_PREFIX = "TicketFlow load fixture"


def ticket_id(index: int):
    return uuid5(NAMESPACE_URL, f"ticketflow/load/ticket/{index}")


def agent_name(index: int) -> str:
    return f"tf_load_agent_{index:02d}"
