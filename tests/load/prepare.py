"""Create a private environment and credentials for an isolated load test stack."""

import json
import os
import secrets
from pathlib import Path

from fixtures import AGENT_COUNT, agent_name

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "backend-drf" / "tmp" / "ticketflow-load"
DEMO_USERS = ("tf_requester", "tf_agent", "tf_agent_other", "tf_admin")
SECRET_KEYS = ("DB_PASSWORD", "REDIS_PASSWORD", "SECRET_KEY", "JWT_SIGNING_KEY", "CAPTCHA_TICKET_SECRET")


def write_once(path: Path, contents: str) -> None:
    try:
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as file:
            file.write(contents)
    except FileExistsError:
        pass


def main() -> None:
    WORK.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    env = env.replace("TF_PORT=8080\n", "TF_PORT=18080\n")
    for key in SECRET_KEYS:
        env = env.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(48)}\n")
    write_once(WORK / ".env", env)
    users = (*DEMO_USERS, *(agent_name(index) for index in range(AGENT_COUNT)))
    write_once(WORK / "accounts.json", json.dumps({name: secrets.token_urlsafe(24) for name in users}) + "\n")
    print(WORK)


if __name__ == "__main__":
    main()
