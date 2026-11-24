import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import jwt
import pytest
from conftest import ARTICLE
from test_ticket_routes import InMemoryRedis, frames

from app.core.config import Settings
from app.core.errors import ProviderError
from app.core.resources import Resources
from app.schemas.assistant import AssistantContext
from app.services.providers import MockProvider, OpenAICompatibleProvider

CHAT = "/ai/v1/assistant/chat/stream"
DRAFT = "/ai/v1/assistant/handoff-draft"
SESSION, QUESTION, ANSWER = (str(uuid4()) for _ in range(3))
INTERNAL = f"/api/assistant/internal/sessions/{SESSION}"
MESSAGE = " VPN 连不上怎么办？ "
REFERENCE = {"article_id": str(ARTICLE), "title": "VPN 排查指南"}
HISTORY = [{"role": "user", "content": "连接报错"}, {"role": "assistant", "content": "请提供报错信息"}]

pytestmark = pytest.mark.anyio


@pytest.fixture
async def assistant(application, signing_key, claims):
    headers = {"Authorization": "Bearer " + jwt.encode(claims, signing_key, algorithm="HS256")}
    context = {"history": list(HISTORY), "categories": ["NETWORK", "OTHER"]}
    question = {
        **context,
        "user_message_id": QUESTION,
        "references": [{**REFERENCE, "excerpt": "先确认客户端已连接。"}],
    }
    calls = []
    errors = {}
    settings = Settings(drf_base_url="http://drf", mock_first_delay=0, mock_chunk_delay=0, mock_chunks=2)
    slots = asyncio.Semaphore(1)

    def drf(request):
        assert request.headers["Authorization"] == headers["Authorization"]
        action = request.url.path.removeprefix(INTERNAL)
        calls.append((action, json.loads(request.content) if request.content else None))
        if action in errors:
            status = errors[action]
            return httpx.Response(status, json={"detail": "DRF error"}, headers={"Retry-After": "9"})
        if action == "/question":
            assert request.method == "POST"
            return httpx.Response(201, json={"code": 1000, "data": question})
        if action == "/answer":
            assert request.method == "POST"
            assert not slots.locked()
            return httpx.Response(200, json={"code": 1000, "data": {"assistant_message_id": ANSWER}})
        assert action == "/context" and request.method == "GET"
        return httpx.Response(200, json={"code": 1000, "data": context})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(drf)) as drf_http,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://ai") as ai,
    ):
        application.state.resources = Resources(settings, drf_http, InMemoryRedis(), slots, MockProvider(settings))
        yield ai, headers, question, calls, errors


@pytest.mark.parametrize("has_references", [True, False])
async def test_chat_stream_persists_complete_answer_and_publishes_metadata(assistant, has_references):
    ai, headers, question, calls, _ = assistant
    if not has_references:
        question["references"] = []
    refs = [REFERENCE] if has_references else []
    response = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": MESSAGE})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    result = frames(response.text)
    assert [event for event, _ in result] == ["meta", "delta", "delta", "done"]
    assert result[0][1] == {"session_id": SESSION, "user_message_id": QUESTION, "references": refs}
    assert result[-1][1] == {"finish_reason": "stop", "assistant_message_id": ANSWER}
    assert calls == [
        ("/question", {"message": MESSAGE}),
        (
            "/answer",
            {
                "user_message_id": QUESTION,
                "content": "".join(data["text"] for event, data in result if event == "delta"),
                "references": refs,
                "status": "complete",
            },
        ),
    ]
    if not has_references:
        assert "知识库中没有找到" in calls[-1][1]["content"]
        assert "转人工提单" in calls[-1][1]["content"]


async def test_assistant_routes_accept_full_drf_context(assistant):
    ai, headers, question, _, _ = assistant
    question["history"][:] = HISTORY * 10
    question["references"] = [
        {"article_id": str(uuid4()), "title": f"VPN 排查指南 {index}", "excerpt": "先确认客户端已连接。"}
        for index in range(5)
    ]

    draft = await ai.post(DRAFT, headers=headers, json={"session_id": SESSION})
    assert draft.status_code == 200
    assert draft.json()["description"] == HISTORY[0]["content"]

    chat = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": MESSAGE})
    assert chat.status_code == 200
    result = frames(chat.text)
    assert result[0][0] == "meta"
    assert len(result[0][1]["references"]) == 5
    assert result[-1][0] == "done"


async def test_chat_queue_timeout_returns_json_before_recording_question(assistant, application):
    ai, headers, _, calls, _ = assistant
    resources = application.state.resources
    settings = resources.settings.model_copy(update={"upstream_slot_timeout": 0.01})
    application.state.resources = replace(resources, settings=settings)

    async with resources.upstream_slots:
        response = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": MESSAGE})

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"] == "UPSTREAM_BUSY"
    assert calls == []


async def test_chat_rejects_whitespace_only_message(assistant):
    ai, headers, _, calls, _ = assistant
    response = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": " \t\n　"})

    assert response.status_code == 422
    assert response.json()["error"] == "VALIDATION_ERROR"
    assert calls == []


@pytest.mark.parametrize("disconnect_after_delta", [False, True])
async def test_chat_disconnect_writes_interrupted_and_releases_slot(
    assistant, application, monkeypatch, disconnect_after_delta
):
    _, headers, _, calls, _ = assistant
    resources = application.state.resources
    disconnected = asyncio.Event()
    upstream_closed = asyncio.Event()
    requested = False
    deltas = []

    async def stream(context, message):
        try:
            yield "正文第一段"
            await asyncio.Future()
        finally:
            upstream_closed.set()

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            body = json.dumps({"session_id": SESSION, "message": MESSAGE}).encode()
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start" and not disconnect_after_delta:
            raise OSError("client disconnected before the first frame")
        if message.get("body", b"").startswith(b"event: delta\n"):
            deltas.append(frames(message["body"].decode())[0][1]["text"])
            disconnected.set()

    monkeypatch.setattr(resources.provider, "stream_chat", stream)
    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.4"},
        "method": "POST",
        "path": CHAT,
        "headers": [(b"content-type", b"application/json"), (b"authorization", headers["Authorization"].encode())],
        "query_string": b"",
    }
    await asyncio.wait_for(application(scope, receive, send), timeout=2)
    assert upstream_closed.is_set() is disconnect_after_delta
    assert not resources.upstream_slots.locked()
    assert calls[-1] == (
        "/answer",
        {"user_message_id": QUESTION, "content": "".join(deltas), "references": [REFERENCE], "status": "interrupted"},
    )


async def test_chat_provider_failure_after_a_delta_persists_partial_without_retry(assistant, application, monkeypatch):
    ai, headers, _, calls, _ = assistant

    async def stream(context, message):
        yield "正文第一段"
        raise ProviderError(503, "LLM_UNAVAILABLE", "模型暂时不可用", retryable=True)

    monkeypatch.setattr(application.state.resources.provider, "stream_chat", stream)
    response = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": MESSAGE})
    result = frames(response.text)
    assert [event for event, _ in result] == ["meta", "delta", "error"]
    assert result[-1][1] == {"code": 503, "error": "LLM_UNAVAILABLE", "detail": "模型暂时不可用", "retryable": True}
    assert calls[-1][1]["status"] == "failed"
    assert calls[-1][1]["content"] == "正文第一段"


@pytest.mark.parametrize("partial", ["", "正文第一段"])
async def test_chat_stream_timeout_persists_failed_and_ends_with_error(assistant, application, monkeypatch, partial):
    ai, headers, _, calls, _ = assistant
    resources = application.state.resources
    settings = resources.settings.model_copy(update={"stream_timeout": 0.2})
    application.state.resources = replace(resources, settings=settings)
    upstream_closed = asyncio.Event()

    async def stream(context, message):
        try:
            if partial:
                yield partial
            await asyncio.Future()
        finally:
            upstream_closed.set()

    monkeypatch.setattr(resources.provider, "stream_chat", stream)
    response = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": MESSAGE})

    assert response.status_code == 200
    result = frames(response.text)
    assert [event for event, _ in result] == (["meta", "delta", "error"] if partial else ["meta", "error"])
    assert result[-1][1] == {"code": 504, "error": "LLM_TIMEOUT", "detail": "模型生成超时", "retryable": False}
    assert calls == [
        ("/question", {"message": MESSAGE}),
        ("/answer", {"user_message_id": QUESTION, "content": partial, "references": [REFERENCE], "status": "failed"}),
    ]
    assert upstream_closed.is_set()


async def test_chat_only_retries_the_idempotent_write_and_never_sends_done_for_failed_write(assistant):
    ai, headers, _, calls, errors = assistant
    body = {"session_id": SESSION, "message": MESSAGE}
    errors["/question"] = 503
    response = await ai.post(CHAT, headers=headers, json=body)
    assert response.status_code == 503
    assert [action for action, _ in calls] == ["/question"]

    calls.clear()
    del errors["/question"]
    errors["/answer"] = 503
    response = await ai.post(CHAT, headers=headers, json=body)
    result = frames(response.text)
    assert [event for event, _ in result] == ["meta", "delta", "delta", "error"]
    assert result[-1][1]["error"] == "DRF_UNAVAILABLE"
    assert [action for action, _ in calls] == ["/question", "/answer", "/answer", "/answer"]
    assert calls[1] == calls[2] == calls[3]


async def test_chat_and_draft_propagate_authorization_and_throttling(assistant):
    ai, headers, _, calls, errors = assistant
    chat_body = {"session_id": SESSION, "message": MESSAGE}
    assert (await ai.post(CHAT, json=chat_body)).status_code == 401
    assert (await ai.post(DRAFT, json={"session_id": SESSION})).status_code == 401
    assert calls == []
    errors.update({"/question": 404, "/context": 429})
    chat = await ai.post(CHAT, headers=headers, json=chat_body)
    draft = await ai.post(DRAFT, headers=headers, json={"session_id": SESSION})
    assert chat.status_code == 404 and chat.json()["error"] == "NOT_FOUND"
    assert draft.status_code == 429 and draft.json()["error"] == "RATE_LIMITED"
    assert draft.headers["Retry-After"] == "9"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"category": "FORGED"},
        {"title": " "},
        {"title": "长" * 201},
        {"description": "描" * 20001},
        {"description": None},
    ],
)
async def test_handoff_draft_uses_json_mode_and_validates_output(assistant, application, fields):
    ai, headers, _, calls, _ = assistant
    resources = application.state.resources
    settings = Settings(mock_llm=False, llm_api_key="test-upstream-key", llm_thinking="enabled")
    valid = {"title": " 需要协助 ", "description": " 连接报错 ", "category": "NETWORK"}

    def llm(request):
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert json.loads(payload["messages"][-1]["content"]) == {
            "history": HISTORY,
            "categories": ["NETWORK", "OTHER"],
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({**valid, **fields})}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(llm)) as upstream:
        application.state.resources = replace(resources, provider=OpenAICompatibleProvider(settings, upstream))
        response = await ai.post(DRAFT, headers=headers, json={"session_id": SESSION})
    assert calls == [("/context", None)]
    if fields:
        assert response.status_code == 502 and response.json()["error"] == "LLM_INVALID_OUTPUT"
    else:
        assert response.status_code == 200
        assert response.json() == {"title": "需要协助", "description": "连接报错", "category": "NETWORK"}


@pytest.mark.parametrize(
    ("history", "expected_history"),
    [
        ([], []),
        (HISTORY, HISTORY),
        (
            [
                {"role": "assistant", "content": "缺少提问的回答"},
                {"role": "user", "content": "先前未答的问题"},
                HISTORY[0],
                HISTORY[1],
                {"role": "assistant", "content": "也请提供系统版本"},
                {"role": "user", "content": "结尾未答的问题"},
            ],
            [
                {"role": "user", "content": "先前未答的问题\n\n连接报错"},
                {"role": "assistant", "content": "请提供报错信息\n\n也请提供系统版本"},
            ],
        ),
        ([{"role": "user", "content": "仅有一个未答的问题"}], []),
    ],
)
async def test_real_provider_chat_prompt_alternates_roles_and_grounds_latest_question(
    assistant, application, history, expected_history
):
    ai, headers, question, _, _ = assistant
    question["history"] = history
    resources = application.state.resources
    settings = Settings(mock_llm=False, llm_api_key="test-upstream-key", llm_thinking="enabled")

    def llm(request):
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["stream"] is True
        instruction, *conversation, latest = payload["messages"]
        assert [message["role"] for message in payload["messages"]] == [
            "system",
            *(["user", "assistant"] * (len(expected_history) // 2)),
            "user",
        ]
        assert "只依据本次提供的知识片段" in instruction["content"]
        assert "知识库中没有找到" in instruction["content"] and "转人工提单" in instruction["content"]
        assert conversation == expected_history
        assert json.loads(latest["content"]) == {
            "question": MESSAGE,
            "references": [{"title": REFERENCE["title"], "excerpt": "先确认客户端已连接。"}],
        }
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"已找到指南"}}]}\n\ndata: [DONE]\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(llm)) as upstream:
        application.state.resources = replace(resources, provider=OpenAICompatibleProvider(settings, upstream))
        response = await ai.post(CHAT, headers=headers, json={"session_id": SESSION, "message": MESSAGE})
    assert frames(response.text)[-1][0] == "done"


async def test_mock_handoff_draft_truncates_long_description():
    provider = MockProvider(Settings(mock_first_delay=0))
    context = AssistantContext(history=[{"role": "user", "content": " 描" + "述" * 20000 + " "}], categories=["OTHER"])

    draft = await provider.handoff_draft(context)

    assert draft.title == "描" + "述" * 199
    assert draft.description == "描" + "述" * 19999
    assert draft.category == "OTHER"
