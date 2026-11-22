import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ACCOUNTS_FILE = Path(__file__).resolve().parents[1] / "deploy" / ".accounts.local.json"


@dataclass(frozen=True, repr=False)
class Session:
    username: str
    access: str
    refresh: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}"}


@pytest.fixture(scope="session")
def gateway():
    url = os.environ.get("TICKETFLOW_GATEWAY_URL", "http://127.0.0.1:8080")
    with httpx.Client(base_url=url, timeout=15) as client:
        yield client


@pytest.fixture(scope="session")
def login(gateway):
    accounts_file = Path(os.environ.get("TICKETFLOW_ACCOUNTS_FILE", ACCOUNTS_FILE))

    def sign_in(username: str) -> Session:
        password = os.environ.get(f"TICKETFLOW_{username.removeprefix('tf_').upper()}_PASSWORD")
        if not password and accounts_file.is_file():
            password = json.loads(accounts_file.read_text(encoding="utf-8")).get(username)
        if not password:
            pytest.fail(f"Missing demo credentials for {username}. See tests/README.md.", pytrace=False)

        response = gateway.post("/api/identity/login/basic", json={"username": username, "password": password})
        assert response.status_code == 200, (
            f"Login for {username}: HTTP {response.status_code}, Retry-After={response.headers.get('Retry-After')}"
        )
        payload = response.json()
        assert payload.get("code") == 1000, f"Login for {username}: code={payload.get('code')}"
        return Session(username, payload["data"]["access"], payload["data"]["refresh"])

    return sign_in


@pytest.fixture(scope="session")
def requester(login):
    return login("tf_requester")


@pytest.fixture(scope="session")
def agent(login):
    return login("tf_agent")


@pytest.fixture(scope="session")
def other_agent(login):
    return login("tf_agent_other")


def create_ticket(gateway, requester):
    unique_id = uuid4().hex
    response = gateway.post(
        "/api/tickets",
        headers={**requester.headers, "Idempotency-Key": unique_id},
        json={
            "title": f"Gateway acceptance {unique_id}",
            "description": "Demo ticket created by the gateway acceptance suite.",
            "category": "ACCOUNT",
            "priority": "P2",
        },
    )
    assert response.status_code == 201, response.text
    envelope = response.json()
    assert envelope["code"] == 1000 and isinstance(envelope["detail"], str)
    data = envelope["data"]
    assert data["status"] == "OPEN"
    return data


@pytest.fixture(scope="session")
def ticket(gateway, requester):
    return create_ticket(gateway, requester)


@pytest.fixture
def transition_ticket(gateway, requester):
    return create_ticket(gateway, requester)
