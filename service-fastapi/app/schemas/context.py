from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ContextTicket(BaseModel):
    id: UUID
    title: str
    description: str
    category: str
    priority: Literal["P0", "P1", "P2", "P3"]
    version: Annotated[int, Field(strict=True, ge=1)]


class Reference(BaseModel):
    article_id: UUID
    title: str


class KnowledgeReference(Reference):
    excerpt: str


class TicketChatTurn(BaseModel):
    role: str
    sender: str
    content: str
    created_time: str = ""


class TicketContext(BaseModel):
    ticket: ContextTicket
    categories: Annotated[list[str], Field(min_length=1)]
    references: list[KnowledgeReference]
    recent_messages: list[TicketChatTurn] = Field(default_factory=list)


class DrfResponse[T](BaseModel):
    code: Literal[1000]
    data: T
