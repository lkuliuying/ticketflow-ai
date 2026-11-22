from typing import Literal

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: int
    error: str
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    redis: Literal["ok"] = "ok"
