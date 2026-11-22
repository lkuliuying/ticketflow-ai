import os
import time
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedUser, get_current_user
from app.core.config import Settings
from app.main import create_app

SIGNING_KEY = "test-only-signing-key-for-ticketflow-ai-with-enough-bytes"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    for name in tuple(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("JWT_SIGNING_KEY", SIGNING_KEY)
    return SIGNING_KEY


@pytest.fixture
def claims():
    now = int(time.time())
    return {
        "aud": "x",
        "iss": "server",
        "exp": now + 300,
        "iat": now - 5,
        "jti": uuid4().hex,
        "user_id": str(uuid4().int % 2**63),
        "token_type": "access",
        "sid": str(uuid4()),
    }


@pytest.fixture
def application():
    app = create_app()

    @app.get("/ai/v1/protected")
    async def protected(user: Annotated[AuthenticatedUser, Depends(get_current_user)], ticket_id: UUID | None = None):
        return {"user_id": user.user_id, "ticket_id": ticket_id}

    return app


@pytest.fixture
def client(application, monkeypatch):
    monkeypatch.setenv("AUTH_REDIS_URL", "redis://127.0.0.1:6379/1")
    with TestClient(application) as client:
        yield client
