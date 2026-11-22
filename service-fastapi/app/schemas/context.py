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


class KnowledgeReference(BaseModel):
    article_id: UUID
    title: str
    excerpt: str


class TicketContext(BaseModel):
    ticket: ContextTicket
    categories: list[str]
    references: list[KnowledgeReference]


class DrfContextResponse(BaseModel):
    code: Literal[1000]
    data: TicketContext
