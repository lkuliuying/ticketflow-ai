"""Collect SQL counts and response digests through the isolated load gateway."""

import argparse
import csv
import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

import httpx
from fixtures import TICKET_COUNT, TITLE_PREFIX, ticket_id
from prepare import ROOT, WORK


class Sample(NamedTuple):
    orm: str
    dashboard_mode: str
    endpoint: str
    SQL: int
    dashboard_cache: str
    data_sha256: str


def select_drf(orm: str, dashboard_mode: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "ticketflow-load",
            "-f",
            "deploy/docker-compose.yml",
            "-f",
            "tests/load/compose.yml",
            "--env-file",
            str(WORK / ".env"),
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "70",
            "drf-web",
        ],
        cwd=ROOT,
        env={**os.environ, "TF_LOAD_ORM": orm, "TF_LOAD_DASHBOARD": dashboard_mode},
        check=True,
    )


def sign_in(client: httpx.Client) -> None:
    password = json.loads((WORK / "accounts.json").read_text(encoding="utf-8"))["tf_agent"]
    response = client.post("/api/identity/login/basic", json={"username": "tf_agent", "password": password})
    response.raise_for_status()
    envelope = response.json()
    if envelope["code"] != 1000:
        raise RuntimeError(f"Login returned code {envelope['code']}")
    client.headers["Authorization"] = f"Bearer {envelope['data']['access']}"


def probe(client: httpx.Client, orm: str, dashboard_mode: str, endpoint: str) -> Sample:
    path, params = {
        "list": ("/api/tickets", {"q": TITLE_PREFIX, "size": 20}),
        "detail": (f"/api/tickets/{ticket_id(0)}", {}),
        "dashboard": ("/api/tickets/dashboard", {"q": TITLE_PREFIX}),
    }[endpoint]
    response = client.get(path, params=params)
    response.raise_for_status()
    envelope = response.json()
    if envelope["code"] != 1000:
        raise RuntimeError(f"{endpoint} returned code {envelope['code']}")
    data = envelope["data"]
    if endpoint == "list":
        valid = data["total"] == TICKET_COUNT and len(data["results"]) == 20
    elif endpoint == "detail":
        valid = data["pk"] == str(ticket_id(0)) and data["timeline"]["total"] == 11
    else:
        valid = sum(data["status"].values()) == TICKET_COUNT
    if not valid:
        raise RuntimeError(f"{endpoint} returned unexpected load fixtures")
    digest = sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    return Sample(
        orm,
        dashboard_mode,
        endpoint,
        int(response.headers["X-Load-Queries"]),
        response.headers.get("X-Load-Dashboard", ""),
        digest,
    )


def sample_tickets(client: httpx.Client, orm: str, dashboard_mode: str) -> list[Sample]:
    samples = []
    for endpoint in ("list", "detail"):
        probe(client, orm, dashboard_mode, endpoint)
        samples.append(probe(client, orm, dashboard_mode, endpoint))
    return samples


def collect(host: str) -> list[Sample]:
    with httpx.Client(base_url=host, trust_env=False, timeout=15) as client:
        select_drf("n+1", "hot")
        sign_in(client)
        baseline = sample_tickets(client, "n+1", "hot")

        select_drf("optimized", "cold")
        optimized = sample_tickets(client, "optimized", "cold")
        cold = [probe(client, "optimized", "cold", "dashboard") for _ in range(2)]

        select_drf("optimized", "hot")
        probe(client, "optimized", "hot", "dashboard")
        hot = [probe(client, "optimized", "hot", "dashboard") for _ in range(2)]

    for before, after in zip(baseline, optimized, strict=True):
        if before.SQL <= after.SQL:
            raise RuntimeError(f"{before.endpoint}: expected more SQL queries in the N+1 variant")
    if any(row.dashboard_cache != "miss" for row in cold) or any(row.dashboard_cache != "hit" for row in hot):
        raise RuntimeError("Dashboard responses did not use the expected cache paths")
    samples = baseline + optimized + cold + hot
    for endpoint in ("list", "detail", "dashboard"):
        if len({sample.data_sha256 for sample in samples if sample.endpoint == endpoint}) != 1:
            raise RuntimeError(f"{endpoint} response data changed between samples")
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    samples = collect(args.host)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(Sample._fields)
        writer.writerows(samples)
    print(f"Wrote {len(samples)} SQL samples to {args.csv}")


if __name__ == "__main__":
    main()
