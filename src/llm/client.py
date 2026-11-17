"""The ONLY gateway to LLMs: Gemini -> Sarvam -> extractive fallback.

Owner: M3 (see CLAUDE.md). Public functions here are listed in CLAUDE.md section 5.

Extractive fallback contract (used when no provider answers with valid JSON):
prompts that carry an ``<evidence>`` block with one item per line, formatted as
``[evidence_id] <metadata> :: <evidence text>``, plus a ``QUESTION:`` block, get an
answer built only by copying evidence text (no LLM). Any other schema gets the most
conservative instance it accepts (``out_of_scope`` / ``insufficient_evidence``).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from pydantic import BaseModel, ValidationError

from src import config

logger = logging.getLogger(__name__)

SARVAM_URL = "https://api.sarvam.ai/v1/chat/completions"
EVIDENCE_LINE_SEP = " :: "
MAX_FALLBACK_SCORECARD_ITEMS = 10
MAX_FALLBACK_CHARTER_ITEMS = 2

_STOPWORDS = frozenset(
    "a an and are as at be been by can could did do does for from had has have how i in is it its "
    "me my of on or our should so than that the their them then there these they this to was we "
    "were what when where which who whom why will with would you your about tell give show please "
    "latest record records say said".split()
)


class LLMUnavailableError(RuntimeError):
    """Raised internally when a provider cannot return a valid response."""


# ------------------------------------------------------------------ public API
def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Return the model response parsed into schema. Tries Gemini, then Sarvam, then an
    extractive (no-LLM) fallback. Never raises to callers. Keys via config.get_secret()."""
    if not prompt or not prompt.strip():
        logger.warning("generate_json called with an empty prompt; using fallback")
        return _extractive_fallback(prompt or "", schema)

    providers = (("gemini", "GEMINI_API_KEY", _call_gemini), ("sarvam", "SARVAM_API_KEY", _call_sarvam))
    for name, key_name, call in providers:
        api_key = config.get_secret(key_name)
        if not api_key:
            logger.info("%s skipped: %s not set", name, key_name)
            continue
        for attempt in range(1 + max(0, config.LLM_MAX_RETRIES)):
            try:
                raw = call(prompt, api_key)
                return parse_json_response(raw, schema)
            except Exception as exc:  # any provider/parse failure -> retry, then next provider
                logger.warning("%s attempt %d failed: %s", name, attempt + 1, exc)
    logger.info("all LLM providers unavailable; using extractive fallback")
    return _extractive_fallback(prompt, schema)


# ------------------------------------------------------------------ parsing
def parse_json_response(raw: str, schema: type[BaseModel]) -> BaseModel:
    """Parse raw model output (possibly fenced or wrapped in prose) into schema.

    Raises LLMUnavailableError when no valid JSON object for the schema is found.
    """
    if not raw or not raw.strip():
        raise LLMUnavailableError("empty response")
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMUnavailableError("no JSON object in response")
    try:
        data = json.loads(text[start : end + 1])
        return schema.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMUnavailableError(f"invalid JSON for {schema.__name__}: {exc}") from exc


# ------------------------------------------------------------------ providers
def _call_gemini(prompt: str, api_key: str) -> str:
    """Call Gemini through the google-genai SDK and return the raw text."""
    from google import genai  # lazy import: tests and offline runs do not need the SDK
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=config.LLM_TIMEOUT_S * 1000))
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=config.LLM_TEMPERATURE,
            response_mime_type="application/json",
        ),
    )
    return response.text or ""


def _call_sarvam(prompt: str, api_key: str) -> str:
    """Call the Sarvam chat-completions endpoint and return the raw text."""
    response = requests.post(
        SARVAM_URL,
        headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
        json={
            "model": config.SARVAM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.LLM_TEMPERATURE,
        },
        timeout=config.LLM_TIMEOUT_S,
    )
    response.raise_for_status()
    choices = response.json().get("choices") or []
    if not choices:
        raise LLMUnavailableError("Sarvam returned no choices")
    content = choices[0].get("message", {}).get("content") or ""
    # sarvam-m may emit a <think>...</think> block before the answer
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)


# ------------------------------------------------------------------ extractive fallback
def _extractive_fallback(prompt: str, schema: type[BaseModel]) -> BaseModel:
    """Build a schema instance without an LLM: copy evidence text, or answer conservatively."""
    fields = schema.model_fields
    if {"status", "text", "citations"} <= set(fields):
        payload = _extractive_answer(prompt)
    else:
        payload = {}
    defaults: dict[str, Any] = {
        "route": "out_of_scope",
        "status": "insufficient_evidence",
        "text": config.FALLBACK_TEXT,
        "reason": "LLM unavailable: conservative fallback",
        "citations": [],
    }
    for key, value in defaults.items():
        if key in fields:
            payload.setdefault(key, value)
    try:
        return schema.model_validate(payload)
    except ValidationError:
        logger.exception("fallback payload invalid for %s; constructing unvalidated", schema.__name__)
        return schema.model_construct(**{k: v for k, v in payload.items() if k in fields})


def _extractive_answer(prompt: str) -> dict[str, Any]:
    """Answer by quoting evidence lines from the prompt; insufficient when nothing relevant."""
    items = _parse_evidence_lines(prompt)
    question_terms = _content_terms(_section(prompt, "QUESTION:"))
    picked: list[tuple[str, str]] = []
    scorecard = [(eid, txt) for eid, meta, txt in items if "scorecard" in meta]
    picked.extend(scorecard[:MAX_FALLBACK_SCORECARD_ITEMS])
    scored: list[tuple[int, str, str]] = []
    for eid, meta, txt in items:
        if "charter" not in meta:
            continue
        sentence, overlap = _best_sentence(txt, question_terms)
        if overlap > 0:
            scored.append((overlap, eid, sentence))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked.extend((eid, sentence) for _, eid, sentence in scored[:MAX_FALLBACK_CHARTER_ITEMS])
    if not picked:
        return {"status": "insufficient_evidence", "text": config.FALLBACK_TEXT, "citations": []}
    text = " ".join(f"{txt} [{eid}]" for eid, txt in picked)
    citations = [{"evidence_id": eid, "claim": txt} for eid, txt in picked]
    return {"status": "answered", "text": text, "citations": citations}


def _section(prompt: str, header: str) -> str:
    """Return the text after a header line, up to the next blank-line-separated header."""
    match = re.search(re.escape(header) + r"\s*\n(.*?)(?:\n\s*\n[A-Z ]+:|\Z)", prompt, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_evidence_lines(prompt: str) -> list[tuple[str, str, str]]:
    """Return (evidence_id, metadata, text) for each evidence line inside <evidence> tags."""
    block = re.search(r"<evidence>(.*?)</evidence>", prompt, flags=re.DOTALL)
    if not block:
        return []
    items: list[tuple[str, str, str]] = []
    for line in block.group(1).splitlines():
        match = re.match(r"\s*\[([^\]]+)\]\s*(.*)$", line)
        if not match or EVIDENCE_LINE_SEP not in match.group(2):
            continue
        meta, text = match.group(2).split(EVIDENCE_LINE_SEP, 1)
        if text.strip():
            items.append((match.group(1).strip(), meta, text.strip()))
    return items


def _content_terms(question: str) -> set[str]:
    """Lower-case content words of the question, ignoring stopwords and initiative names
    (all-caps acronyms and NIM ids), which match every chunk of that initiative."""
    terms: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z\-]+", question):
        if token.isupper() or token.lower().startswith("nim") or token.lower() in _STOPWORDS:
            continue
        if len(token) >= 3:
            terms.add(_stem(token.lower()))
    return terms


def _stem(word: str) -> str:
    """Very light stemming so 'risks'/'risk' and 'rated'/'rating' overlap."""
    for suffix in ("ings", "ing", "ies", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _best_sentence(text: str, terms: set[str]) -> tuple[str, int]:
    """Return the sentence of text with the most question-term overlap, and that overlap."""
    best, best_overlap = text, 0
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = {_stem(w.lower()) for w in re.findall(r"[A-Za-z][A-Za-z\-]+", sentence)}
        overlap = len(words & terms)
        if overlap > best_overlap:
            best, best_overlap = sentence.strip(), overlap
    return best, best_overlap
