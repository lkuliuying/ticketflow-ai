"""Write the settings for this container, then run its process."""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml


def write_config() -> None:
    env = os.environ
    if env["SECRET_KEY"] == env["JWT_SIGNING_KEY"]:
        raise SystemExit("SECRET_KEY and JWT_SIGNING_KEY must be different")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", env["REDIS_PASSWORD"]):
        raise SystemExit("REDIS_PASSWORD must contain only letters, digits, underscores or hyphens")
    mode = env["TICKETFLOW_DEMO"].lower()
    if mode not in {"true", "false"}:
        raise SystemExit("TICKETFLOW_DEMO must be true or false")
    demo = mode == "true"
    hosts = [host.strip() for host in env["TF_ALLOWED_HOSTS"].split(",") if host.strip()]
    config = {
        "SECRET_KEY": env["SECRET_KEY"],
        "JWT_SIGNING_KEY": env["JWT_SIGNING_KEY"],
        "CAPTCHA_TICKET_SECRET": env["CAPTCHA_TICKET_SECRET"],
        "CAPTCHA_TICKET_AUDIENCE": env["CAPTCHA_TICKET_AUDIENCE"],
        "ALLOWED_HOSTS": ["drf-web", "127.0.0.1", *hosts],
        "DEBUG": False,
        "AUTO_MIGRATE": False,
        "XADMIN_APPS": ["tickets", "knowledge"],
        "DB_HOST": "postgres",
        "DB_DATABASE": "ticketflow",
        "DB_USER": "ticketflow",
        "DB_PASSWORD": env["DB_PASSWORD"],
        "REDIS_HOST": "redis",
        "REDIS_PASSWORD": env["REDIS_PASSWORD"],
        "DEFAULT_CACHE_ID": 1,
        "SECURITY_LOGIN_CAPTCHA_ENABLED": not demo,
        "SECURITY_LOGIN_TEMP_TOKEN_ENABLED": not demo,
        "SECURITY_LOGIN_ENCRYPTED_ENABLED": not demo,
    }
    # The upstream Dockerfile leaves a blank config.yml in the image.
    path = Path("config.yml.tmp")
    with open(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600),
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(config, file)
    path.replace("config.yml")


def main() -> None:
    write_config()
    if sys.argv[1:] == ["init"]:
        subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)
        subprocess.run(
            [
                sys.executable,
                "manage.py",
                "shell",
                "--no-imports",
                "--command",
                "from ops.seed_ticketflow_demo import ensure_seed_owner; ensure_seed_owner()",
            ],
            check=True,
        )
        os.execv(sys.executable, [sys.executable, "manage.py", "load_init_json"])
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
