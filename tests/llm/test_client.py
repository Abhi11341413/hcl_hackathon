"""Tests for src.llm.client (owner: M3). No real API calls: providers are mocked."""
from __future__ import annotations

import pytest
from pydantic import BaseModel

import src.llm.client as client
from src import config
from src.contracts import Citation, RouteDecision


class Draft(BaseModel):
    status: str
    text: str
    citations: list[Citation] = []


PROMPT = (
    "QUESTION:\nWhat risks does the charter record for EPS?\n\nEVIDENCE:\n<evidence>\n"
    "[sc-1] kind=scorecard | initiative=NIM-04 | metric=roi | source=scorecard :: EPS ROI is 5.0%.\n"
    "[ch-1] kind=charter | initiative=NIM-04 | source=EPS.docx#6 :: Overview text. "
    "Key risks are vendor lock-in and low adoption.\n"
    "[ch-2] kind=charter | initiative=NIM-04 | source=EPS.docx#2 :: The portal serves citizens.\n"
    "</evidence>\n"
)


@pytest.fixture
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: None)


@pytest.fixture
def gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: "k" if name == "GEMINI_API_KEY" else None)


def test_gemini_success_parses_fenced_json(gemini_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_call_gemini", lambda p, k: '```json\n{"status":"answered","text":"x"}\n```')
    out = client.generate_json("prompt", Draft)
    assert isinstance(out, Draft) and out.text == "x"


def test_falls_back_to_sarvam_when_gemini_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: "k")

    def boom(prompt: str, key: str) -> str:
        raise RuntimeError("quota")

    monkeypatch.setattr(client, "_call_gemini", boom)
    monkeypatch.setattr(client, "_call_sarvam", lambda p, k: '{"route": "numeric", "reason": "s"}')
    out = client.generate_json("prompt", RouteDecision)
    assert isinstance(out, RouteDecision) and out.route == "numeric"


def test_invalid_json_everywhere_uses_fallback_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: "k")
    monkeypatch.setattr(client, "_call_gemini", lambda p, k: "not json")
    monkeypatch.setattr(client, "_call_sarvam", lambda p, k: '{"route": "invented"}')
    out = client.generate_json("prompt", RouteDecision)
    assert out.route == "out_of_scope"


def test_no_keys_extractive_answer_quotes_relevant_evidence(no_keys: None) -> None:
    out = client.generate_json(PROMPT, Draft)
    assert out.status == "answered"
    ids = [c.evidence_id for c in out.citations]
    assert ids[0] == "sc-1" and "ch-1" in ids and "ch-2" not in ids
    assert "Key risks are vendor lock-in and low adoption." in out.text


def test_no_keys_without_evidence_is_insufficient(no_keys: None) -> None:
    out = client.generate_json("QUESTION:\nWho built it?\n\nEVIDENCE:\n<evidence>\n</evidence>", Draft)
    assert out.status == "insufficient_evidence" and out.text == config.FALLBACK_TEXT


def test_empty_prompt_does_not_raise(no_keys: None) -> None:
    assert client.generate_json("", RouteDecision).route == "out_of_scope"


def test_parse_json_response_rejects_garbage() -> None:
    with pytest.raises(client.LLMUnavailableError):
        client.parse_json_response("", Draft)
    with pytest.raises(client.LLMUnavailableError):
        client.parse_json_response("no braces here", Draft)


def test_call_sarvam_strips_think_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: None)
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "<think>hmm</think>{\"a\": 1}"}}]}

    captured: dict = {}

    def fake_post(url: str, **kwargs: object) -> FakeResponse:
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(client.requests, "post", fake_post)
    assert client._call_sarvam("hi", "key").strip() == '{"a": 1}'
    assert captured["json"]["model"] == config.SARVAM_MODEL
    assert captured["json"]["temperature"] == config.LLM_TEMPERATURE
    assert captured["json"]["reasoning_effort"] == client.SARVAM_REASONING_EFFORT


def test_model_name_override_from_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: " gemini-new " if name == "GEMINI_MODEL" else None)
    assert client.model_name("GEMINI_MODEL", "old") == "gemini-new"
    assert client.model_name("SARVAM_MODEL", "sarvam-default") == "sarvam-default"


def test_permanent_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: "k" if name.endswith("_API_KEY") else None)
    calls = {"gemini": 0}

    class NotFound(Exception):
        code = 404

    def gone(prompt: str, key: str) -> str:
        calls["gemini"] += 1
        raise NotFound("model retired")

    monkeypatch.setattr(client, "_call_gemini", gone)
    monkeypatch.setattr(client, "_call_sarvam", lambda p, k: '{"route": "narrative"}')
    assert client.generate_json("prompt", RouteDecision).route == "narrative"
    assert calls["gemini"] == 1


def test_is_permanent_error_reads_http_status() -> None:
    class Resp:
        status_code = 503

    class Busy(Exception):
        response = Resp()

    assert not client.is_permanent_error(Busy("overloaded"))
    assert not client.is_permanent_error(RuntimeError("timeout"))


def test_sarvam_empty_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_secret", lambda name: None)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}

    monkeypatch.setattr(client.requests, "post", lambda url, **kw: FakeResponse())
    with pytest.raises(client.LLMUnavailableError):
        client._call_sarvam("hi", "key")
