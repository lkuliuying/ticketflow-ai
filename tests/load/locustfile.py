"""Drive one TicketFlow scenario per Locust process through the delivery gateway."""

import csv
import json
import os
from itertools import count
from pathlib import Path
from time import perf_counter

import requests
from fixtures import TICKET_COUNT, TITLE_PREFIX, agent_name, ticket_id
from gevent.event import Event
from locust import HttpUser, events, task
from locust.exception import StopUser
from locust.stats import PERCENTILES_TO_REPORT, StatsCSV
from prepare import WORK

ANALYSIS = "/ai/v1/tickets/analyze"
STREAM = "/ai/v1/tickets/suggest-reply/stream"
DETAIL_ID = str(ticket_id(0))
INDEXES = count()
TICKETS = count()
READY = Event()
SIGNED_IN = count(1)
ACCOUNT_START = int(os.environ.get("TF_LOAD_ACCOUNT_START", "0"))
SCENARIO = os.environ.get("TF_LOAD_SCENARIO", "list")
DASHBOARD_MODE = os.environ.get("TF_LOAD_DASHBOARD", "hot")


@events.init.add_listener
def capture_final_csv(environment, **kwargs):
    prefix = environment.parsed_options.csv_prefix
    if prefix is None:
        return

    @environment.events.quit.add_listener
    def write_final_results(exit_code):
        # The periodic Locust CSV writer can finish before the last in-flight request.
        report = StatsCSV(environment, PERCENTILES_TO_REPORT)
        for suffix, write in (("stats", report.requests_csv), ("failures", report.failures_csv)):
            with Path(f"{prefix}_final_{suffix}.csv").open("w", encoding="utf-8", newline="") as file:
                write(csv.writer(file))


def elapsed_ms(start):
    return (perf_counter() - start) * 1000


class GatewayUser(HttpUser):
    def on_start(self):
        username = agent_name(ACCOUNT_START + next(INDEXES)) if SCENARIO in {"analysis", "sse"} else "tf_agent"
        try:
            passwords = json.loads((WORK / "accounts.json").read_text(encoding="utf-8"))
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(
                    f"{self.host}/api/identity/login/basic",
                    json={"username": username, "password": passwords[username]},
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
                if payload["code"] != 1000:
                    raise ValueError(f"login code={payload['code']}")
                self.client.headers["Authorization"] = f"Bearer {payload['data']['access']}"
                if SCENARIO == "dashboard" and DASHBOARD_MODE == "hot":
                    # Populate the shared dashboard key outside Locust's timed requests.
                    warm = session.get(
                        f"{self.host}/api/tickets/dashboard",
                        params={"q": TITLE_PREFIX},
                        headers=self.client.headers,
                        timeout=15,
                    )
                    warm.raise_for_status()
            if next(SIGNED_IN) == self.environment.parsed_options.num_users:
                self.environment.stats.reset_all()
                READY.set()
            if not READY.wait(timeout=30):
                raise ValueError("Not all virtual users completed login and warm-up")
        except (OSError, KeyError, ValueError, requests.RequestException) as exc:
            self.environment.process_exit_code = 1
            self.environment.events.user_error.fire(user_instance=self, exception=exc, tb=exc.__traceback__)
            raise StopUser() from exc

    def timing(self, name, value):
        self.environment.events.request.fire(
            request_type="TIMING", name=name, response_time=value, response_length=0, exception=None
        )

    def record_queue(self, response):
        for metric in response.headers.get("Server-Timing", "").split(","):
            if metric.strip().startswith("upstream-queue;dur="):
                self.timing(f"{SCENARIO} slot wait", float(metric.split("=", 1)[1]))
                return True
        return False

    @task
    def exercise(self):
        if SCENARIO == "analysis":
            self.analyze()
        elif SCENARIO == "sse":
            self.stream()
        else:
            self.read_drf()

    def read_drf(self):
        path, params = {
            "list": ("/api/tickets", {"q": TITLE_PREFIX, "size": 20}),
            "detail": (f"/api/tickets/{DETAIL_ID}", {}),
            "dashboard": ("/api/tickets/dashboard", {"q": TITLE_PREFIX}),
        }[SCENARIO]
        with self.client.get(path, name=SCENARIO, params=params, catch_response=True, timeout=15) as response:
            if not self.expected_status(response):
                return
            envelope = response.json()
            data = envelope["data"]
            valid = {
                "list": lambda: data["total"] == TICKET_COUNT and len(data["results"]) == 20,
                "detail": lambda: data["pk"] == DETAIL_ID and data["timeline"]["total"] == 11,
                "dashboard": lambda: sum(data["status"].values()) == TICKET_COUNT,
            }[SCENARIO]()
            if envelope["code"] != 1000 or not valid:
                response.failure("Unexpected ticket data")
            elif SCENARIO == "dashboard":
                expected = "hit" if DASHBOARD_MODE == "hot" else "miss"
                actual = response.headers.get("X-Load-Dashboard")
                if actual != expected:
                    response.failure(f"Dashboard {actual}; expected {expected}")

    @staticmethod
    def expected_status(response):
        if response.status_code != 200:
            if response.status_code:
                response.failure(f"HTTP {response.status_code}: {response.text[:240]}")
            return False
        return True

    def analyze(self):
        index = next(TICKETS)
        if index >= TICKET_COUNT:
            self.environment.process_exit_code = 1
            raise StopUser()
        pk = str(ticket_id(index))
        with self.client.post(
            ANALYSIS, name="analysis", json={"ticket_id": pk}, catch_response=True, timeout=15
        ) as response:
            measured = self.record_queue(response)
            if self.expected_status(response) and (not measured or response.json()["ticket_id"] != pk):
                response.failure("Analysis bypassed the upstream slot or returned another ticket")

    def stream(self):
        start = perf_counter()
        with self.client.post(
            STREAM, name="sse complete", json={"ticket_id": DETAIL_ID}, stream=True, catch_response=True, timeout=15
        ) as response:
            measured = self.record_queue(response)
            try:
                if self.expected_status(response):
                    if measured:
                        self.read_events(response, start)
                    else:
                        response.failure("SSE response is missing upstream slot timing")
            except (requests.RequestException, ValueError) as exc:
                response.failure(str(exc))
            finally:
                response.request_meta["response_time"] = elapsed_ms(start)
                response.close()

    def read_events(self, response, start):
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
            response.failure("Expected an SSE response")
            return
        event = None
        first_delta = False
        for line in response.iter_lines(chunk_size=256):
            if line.startswith(b"event: "):
                event = line[7:]
            elif line.startswith(b"data: "):
                payload = json.loads(line[6:])
                if event == b"delta" and not first_delta and payload.get("text"):
                    self.timing("sse first delta", elapsed_ms(start))
                    first_delta = True
                elif event == b"done" and first_delta:
                    self.timing("sse done", elapsed_ms(start))
                    return
                elif event == b"error":
                    response.failure(f"SSE error: {payload}")
                    return
        response.failure("SSE ended without first delta and done")
