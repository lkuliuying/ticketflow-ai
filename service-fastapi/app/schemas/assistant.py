from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.context import KnowledgeReference, Reference

MAX_ANSWER_LENGTH = 20000
MAX_HANDOFF_DESCRIPTION_LENGTH = 20000
AnswerStatus = Literal["complete", "interrupted", "failed"]


class HandoffRequest(BaseModel):
    session_id: UUID


class ChatRequest(HandoffRequest):
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000, pattern=r"\S")]


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistantContext(BaseModel):
    history: Annotated[list[HistoryMessage], Field(max_length=20)]
    categories: Annotated[list[str], Field(min_length=1)]


class QuestionContext(AssistantContext):
    user_message_id: UUID
    references: Annotated[list[KnowledgeReference], Field(max_length=5)]


class AnswerInput(BaseModel):
    user_message_id: UUID
    content: Annotated[str, StringConstraints(max_length=MAX_ANSWER_LENGTH)]
    references: list[Reference]
    status: AnswerStatus


class AnswerResult(BaseModel):
    assistant_message_id: UUID


class ChatMeta(BaseModel):
    session_id: UUID
    user_message_id: UUID
    references: list[Reference]


class HandoffDraft(BaseModel):
    model_config = ConfigDict(strict=True, revalidate_instances="always", hide_input_in_errors=True)

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_HANDOFF_DESCRIPTION_LENGTH)
    ]
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
