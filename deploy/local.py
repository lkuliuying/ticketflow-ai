"""Prepare a local Compose environment or send demo credentials to Django."""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent
ACCOUNTS = DEPLOY / ".accounts.local.json"
USERS = ("tf_requester", "tf_agent", "tf_agent_other", "tf_admin")
SECRET_KEYS = (
    "DB_PASSWORD",
    "REDIS_PASSWORD",
    "SECRET_KEY",
    "JWT_SIGNING_KEY",
    "CAPTCHA_TICKET_SECRET",
)


def create_private_file(path: Path, text: str) -> None:
    with open(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
        "w",
        encoding="utf-8",
    ) as file:
        file.write(text)


def create_env() -> None:
    env = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    for key in SECRET_KEYS:
        env = env.replace(f"{key}=\n", f"{key}={secrets.token_urlsafe(48)}\n")
    try:
        create_private_file(DEPLOY / ".env", env)
    except FileExistsError:
        raise SystemExit("deploy/.env already exists") from None
    print("Created deploy/.env")


def seed() -> None:
    if not ACCOUNTS.exists():
        users = {user: secrets.token_urlsafe(24) for user in USERS}
        try:
            create_private_file(ACCOUNTS, json.dumps(users, indent=2) + "\n")
        except FileExistsError:
            pass
    with ACCOUNTS.open("rb") as credentials:
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "--env-file",
                ".env",
                "exec",
                "-T",
                "drf-web",
                "python",
                "manage.py",
                "shell",
                "--no-imports",
                "--command",
                "from ops.seed_ticketflow_demo import main; main()",
            ],
            cwd=DEPLOY,
            stdin=credentials,
            check=True,
        )
    print("Demo credentials: deploy/.accounts.local.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("env", "seed"))
    args = parser.parse_args()
    {"env": create_env, "seed": seed}[args.command]()
