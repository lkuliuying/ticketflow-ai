from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

Priority = Literal["P0", "P1", "P2", "P3"]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


def unique_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tags))


class TicketRequest(BaseModel):
    ticket_id: UUID


class AnalysisDraft(BaseModel):
    model_config = ConfigDict(strict=True, revalidate_instances="always", hide_input_in_errors=True)

    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    suggested_priority: Priority
    summary: Summary
    tags: Annotated[
        list[Tag], AfterValidator(unique_tags), Field(max_length=12, json_schema_extra={"uniqueItems": True})
    ]


class AnalysisResponse(AnalysisDraft):
    ticket_id: UUID
    ticket_version: Annotated[int, Field(ge=1)]


class StreamReference(BaseModel):
    article_id: UUID
    title: str


class StreamMeta(BaseModel):
    ticket_id: UUID
    ticket_version: Annotated[int, Field(ge=1)]
    references: list[StreamReference]
