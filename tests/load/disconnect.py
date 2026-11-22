"""Disconnect after the first delta while every upstream slot is occupied."""

import argparse
import asyncio
import csv
import json
from contextlib import AsyncExitStack
from pathlib import Path
from time import perf_counter

import httpx
from fixtures import agent_name, ticket_id
from prepare import WORK


async def sign_in(client, passwords, index):
    username = agent_name(index)
    response = await client.post(
        "/api/identity/login/basic", json={"username": username, "password": passwords[username]}
    )
    response.raise_for_status()
    envelope = response.json()
    assert envelope["code"] == 1000
    return {"Authorization": f"Bearer {envelope['data']['access']}"}


async def wait_for_delta(lines):
    async for line in lines:
        if line == "event: delta":
            return
        if line in {"event: done", "event: error"}:
            break
    raise RuntimeError("Stream closed without a delta")


async def probe(host):
    passwords = json.loads((WORK / "accounts.json").read_text(encoding="utf-8"))
    samples = []
    clock = perf_counter
    async with httpx.AsyncClient(base_url=host, timeout=10, trust_env=False) as client:
        sessions = await asyncio.gather(*(sign_in(client, passwords, index) for index in range(28, 32)))
        started = clock()

        async def sample(phase):
            response = await client.get("/ai/v1/load-slots")
            response.raise_for_status()
            result = response.json()
            samples.append({"phase": phase, "elapsed_ms": round((clock() - started) * 1000, 3), **result})
            return result

        idle = await sample("before")
        assert idle["available"] == idle["capacity"] == len(sessions)
        async with AsyncExitStack() as stack:
            streams = await asyncio.gather(
                *(
                    stack.enter_async_context(
                        client.stream(
                            "POST",
                            "/ai/v1/tickets/suggest-reply/stream",
                            headers=session,
                            json={"ticket_id": str(ticket_id(0))},
                        )
                    )
                    for session in sessions
                )
            )
            for stream in streams:
                stream.raise_for_status()
            # Retain each iterator until the response context explicitly closes its connection.
            lines = [stream.aiter_lines() for stream in streams]
            await asyncio.gather(*(wait_for_delta(iterator) for iterator in lines))
            occupied = await sample("after_first_delta")
            assert occupied["in_use"] == idle["capacity"], occupied
            disconnected = clock()

        async with asyncio.timeout(0.8):
            while (await sample("after_disconnect"))["available"] < idle["capacity"]:
                await asyncio.sleep(0.02)
        samples[-1]["released_after_ms"] = round((clock() - disconnected) * 1000, 3)
        health = await client.get("/ai/v1/health")
        health.raise_for_status()
        assert health.json() == {"status": "ok", "redis": "ok"}
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    samples = asyncio.run(probe(args.host))
    with args.csv.open("w", encoding="utf-8", newline="") as file:
        fields = [*samples[0], "released_after_ms"]
        writer = csv.DictWriter(file, fields)
        writer.writeheader()
        writer.writerows(samples)
    print(f"Restored {samples[-1]['available']} slots in {samples[-1]['released_after_ms']} ms")


if __name__ == "__main__":
    main()
