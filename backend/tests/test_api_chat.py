from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.chat.chat_service import ChatService
from backend.app.main import create_app
from backend.app.pipeline.jobs import AnalysisJobManager
from backend.tests.api_fixtures import TEST_SETTINGS, FakeAnalyzer, fake_lookup, memory_session_factory, run_now
from backend.tests.test_chat_service import ScriptedClient, completion, settings, tool_call
from backend.tests.test_chat_tools import FakeQuotes


def chat_api(*responses, **setting_overrides):
    client = ScriptedClient(*responses)
    analyzer = FakeAnalyzer()
    app = create_app(
        settings=TEST_SETTINGS, session_factory=memory_session_factory(), analyzer=analyzer,
        stock_lookup=fake_lookup, jobs=AnalysisJobManager(run_now), quote_provider=FakeQuotes(),
        chat_service=ChatService(settings=settings(**setting_overrides), client=client),
    )
    api = TestClient(app)
    api.llm, api.analyzer = client, analyzer
    return api


def test_chat_creates_session_and_history():
    api = chat_api(completion("你好"))

    response = api.post("/api/chat", json={"message": "嗨"})

    assert response.status_code == 200
    body = response.json()
    session_id = body["session_id"]
    assert len(session_id) == 32 and body["reply"] == "你好"
    history = api.get("/api/chat/history", params={"session_id": session_id}).json()
    assert [(m["role"], m["content"]) for m in history["messages"]] == [("user", "嗨"), ("assistant", "你好")]
    assert history["pending_actions"] == []


def test_confirm_flow_executes_analysis_only_after_button():
    api = chat_api(completion(tool_calls=[tool_call("analyze_stock", {"stock_id": "2330"})]), completion("請按確認"))

    body = api.post("/api/chat", json={"session_id": "abc", "message": "分析2330"}).json()

    assert api.analyzer.calls == []  # LLM 呼叫後尚未執行
    action_id = body["pending_actions"][0]["id"]
    assert body["pending_actions"][0]["summary"].startswith("分析 2330 台積電")

    confirmed = api.post(f"/api/chat/actions/{action_id}/confirm", json={})

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "done"
    assert confirmed.json()["message"].startswith("已完成分析：2330 台積電")
    assert api.analyzer.calls == ["2330"]
    assert api.get("/api/reports/2330/latest").status_code == 200
    history = api.get("/api/chat/history", params={"session_id": "abc"}).json()
    assert history["messages"][-1]["role"] == "action" and history["pending_actions"] == []
    assert api.post(f"/api/chat/actions/{action_id}/confirm", json={}).status_code == 409


def test_cancel_action():
    api = chat_api(completion(tool_calls=[tool_call("analyze_stock", {"stock_id": "2330"})]), completion("請按確認"))
    action_id = api.post("/api/chat", json={"session_id": "abc", "message": "分析2330"}).json()["pending_actions"][0]["id"]

    response = api.post(f"/api/chat/actions/{action_id}/cancel", json={})

    assert response.json()["status"] == "cancelled" and api.analyzer.calls == []


def test_unknown_action_404():
    api = chat_api()

    response = api.post(f"/api/chat/actions/{'0' * 32}/confirm", json={})

    assert response.status_code == 404 and response.json()["error"] == "ActionNotFoundError"


def test_chat_without_key_is_503():
    api = chat_api(openai_api_key=None)

    response = api.post("/api/chat", json={"message": "嗨"})

    assert response.status_code == 503 and response.json()["error"] == "ChatNotConfiguredError"


@pytest.mark.parametrize("payload", [
    {"message": ""},
    {"message": "嗨", "session_id": "../etc"},
    {"message": "嗨", "session_id": "x" * 65},
])
def test_invalid_chat_input_422(payload):
    assert chat_api(completion("x")).post("/api/chat", json=payload).status_code == 422


def test_confirm_requires_json_post():
    api = chat_api()

    response = api.post(f"/api/chat/actions/{'0' * 32}/confirm", data={"x": "1"})

    assert response.status_code == 415


def test_chat_endpoints_declare_json_body_for_swagger():
    openapi = chat_api().get("/openapi.json").json()["paths"]

    for path in ("/api/chat", "/api/chat/actions/{action_id}/confirm", "/api/chat/actions/{action_id}/cancel"):
        assert "application/json" in openapi[path]["post"]["requestBody"]["content"]


def test_history_hides_tool_logs():
    api = chat_api(completion(tool_calls=[tool_call("list_watchlist", {})]), completion("清單是空的"))
    session_id = api.post("/api/chat", json={"message": "清單"}).json()["session_id"]

    roles = [m["role"] for m in api.get("/api/chat/history", params={"session_id": session_id}).json()["messages"]]

    assert roles == ["user", "assistant"]
