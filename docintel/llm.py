"""OpenRouter client. One function to call, one to extract.

Shapes (verified against OpenRouter docs 2026-10-26):
- response_format = {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}
- PDF: a user content part {"type": "file", "file": {"filename", "file_data": "data:application/pdf;base64,..."}}
  plus plugins=[{"id": "file-parser", "pdf": {"engine": "native" | "mistral-ocr" | "cloudflare-ai"}}]
- usage={"include": true} returns usage.cost in USD.
Transport is injectable so tests never touch the network.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Callable

import httpx
from pydantic import ValidationError

from .config import settings
from .prompts import EXTRACT_SYSTEM, MAP_TABLE_SYSTEM, PROMPT_VERSION, user_image_block, user_pdf_block, user_table_block, user_text_block
from .schema import Extraction, TableMapping, extraction_json_schema

log = logging.getLogger("docintel.llm")
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
Transport = Callable[[dict[str, Any]], dict[str, Any]]
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


class CostCapReached(LLMError):
    pass


def spend_today() -> float:
    """USD spent since 00:00 UTC, from llm_calls."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from .db import SessionLocal
    from .models import LLMCall

    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    with SessionLocal() as s:
        return float(s.execute(select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(LLMCall.created_at >= start)).scalar() or 0.0)


def check_cost_cap() -> None:
    cap = settings.daily_cost_cap_usd
    if cap and cap > 0:
        spent = spend_today()
        if spent >= cap:
            raise CostCapReached(f"Daily cost cap reached: ${spent:.2f} of ${cap:.2f} spent today. Raise DAILY_COST_CAP_USD or wait for tomorrow.")


def _post(body: dict[str, Any], timeout: float = 240.0) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": settings.base_url,
        "X-Title": "Drive DocIntel",
    }
    r = httpx.post(ENDPOINT, json=body, headers=headers, timeout=timeout)
    if r.status_code in RETRYABLE:
        raise httpx.HTTPStatusError(f"{r.status_code}: {r.text[:300]}", request=r.request, response=r)
    if r.status_code >= 400:
        raise LLMError(f"OpenRouter {r.status_code}: {r.text[:500]}")
    return r.json()


def complete(body: dict[str, Any], *, transport: Transport | None = None, retries: int = 2) -> dict[str, Any]:
    """POST with retries on transport errors / 5xx / 429. Returns the raw JSON response."""
    send = transport or _post
    if transport is None:
        check_cost_cap()
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            data = send(body)
            if "error" in data and not data.get("choices"):
                raise LLMError(f"OpenRouter error: {json.dumps(data['error'])[:500]}")
            return data
        except (httpx.HTTPError, LLMError) as exc:
            last = exc
            if isinstance(exc, LLMError) and "OpenRouter error" not in str(exc) and "429" not in str(exc):
                raise
            if attempt == retries:
                break
            log.warning("llm retry %d after %s", attempt + 1, type(exc).__name__)
            time.sleep(delay)
            delay *= 2
    raise LLMError(str(last))


def stream_complete(body: dict[str, Any], *, on_delta: Callable[[str], None], transport: Transport | None = None,
                    retries: int = 2, timeout: float = 300.0) -> dict[str, Any]:
    """Same request with stream=true. Content deltas go to on_delta as they arrive; tool-call fragments are
    reassembled. Returns a response shaped like the non-streaming one so callers need not care."""
    if transport is not None:  # tests and fakes: no network, no streaming
        data = transport(body)
        text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content")
        if isinstance(text, str) and text:
            on_delta(text)
        return data
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    check_cost_cap()
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}", "HTTP-Referer": settings.base_url, "X-Title": "Drive DocIntel"}
    req = {**body, "stream": True}
    delay = 2.0
    for attempt in range(retries + 1):
        parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish, usage, model = "", {}, ""
        try:
            with httpx.stream("POST", ENDPOINT, json=req, headers=headers, timeout=timeout) as r:
                if r.status_code in RETRYABLE:
                    r.read()
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    r.read()
                    raise LLMError(f"OpenRouter {r.status_code}: {r.text[:500]}")
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue  # keep-alive comments such as ": OPENROUTER PROCESSING"
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if "error" in chunk and not chunk.get("choices"):
                        raise LLMError(f"OpenRouter error: {json.dumps(chunk['error'])[:500]}")
                    model = chunk.get("model") or model
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for ch in chunk.get("choices") or []:
                        delta = ch.get("delta") or {}
                        text = delta.get("content")
                        if text:
                            parts.append(text)
                            on_delta(text)
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(int(tc.get("index", 0)), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["function"]["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["function"]["arguments"] += fn["arguments"]
                        if ch.get("finish_reason"):
                            finish = ch["finish_reason"]
            msg: dict[str, Any] = {"content": "".join(parts)}
            if calls:
                msg["tool_calls"] = [calls[i] for i in sorted(calls)]
            return {"model": model, "choices": [{"message": msg, "finish_reason": finish}], "usage": usage}
        except (httpx.HTTPError, LLMError) as exc:
            if parts or attempt == retries or (isinstance(exc, LLMError) and "429" not in str(exc) and "OpenRouter error" not in str(exc)):
                raise LLMError(str(exc)) from exc
            log.warning("stream retry %d after %s", attempt + 1, type(exc).__name__)
            time.sleep(delay)
            delay *= 2
    raise LLMError("stream failed")


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    u = data.get("usage") or {}
    return {
        "input_tokens": int(u.get("prompt_tokens") or 0),
        "output_tokens": int(u.get("completion_tokens") or 0),
        "cost_usd": float(u.get("cost") or 0.0),
    }


def _content_text(data: dict[str, Any]) -> str:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):  # some providers return parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    if not isinstance(content, str) or not content.strip():
        raise LLMError(f"empty model content (finish_reason={choice.get('finish_reason')})")
    return content


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def extract(
    name: str,
    *,
    pdf_bytes: bytes | None = None,
    image: tuple[bytes, str] | None = None,
    text: str | None = None,
    kind: str = "document",
    engine: str | None = None,
    effort: str | None = None,
    model: str | None = None,
    transport: Transport | None = None,
) -> tuple[Extraction, dict[str, Any]]:
    """Run the extraction schema over one document. Returns (Extraction, meta)."""
    if sum(x is not None for x in (pdf_bytes, image, text)) != 1:
        raise ValueError("pass exactly one of pdf_bytes, image or text")
    model = model or settings.model
    engine = engine or settings.pdf_engine
    user_parts: list[dict[str, Any]] = []
    if pdf_bytes is not None:
        b64 = base64.b64encode(pdf_bytes).decode()
        user_parts.append({"type": "text", "text": user_pdf_block(name)})
        user_parts.append({"type": "file", "file": {"filename": name, "file_data": f"data:application/pdf;base64,{b64}"}})
    elif image is not None:
        data_b, mime = image
        user_parts.append({"type": "text", "text": user_image_block(name)})
        user_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data_b).decode()}"}})
    else:
        user_parts.append({"type": "text", "text": user_text_block(name, kind, text or "")})

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": EXTRACT_SYSTEM, "cache_control": {"type": "ephemeral"}}]},
            {"role": "user", "content": user_parts},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "extraction", "strict": True, "schema": extraction_json_schema()}},
        "provider": {"require_parameters": True, "data_collection": "deny"},
        "reasoning": {"effort": effort or settings.reasoning_effort},
        "usage": {"include": True},
        "max_tokens": 16000,
    }
    if settings.fallback_model and settings.fallback_model != model:
        body["models"] = [model, settings.fallback_model]
    if pdf_bytes is not None:
        body["plugins"] = [{"id": "file-parser", "pdf": {"engine": engine}}]

    started = time.perf_counter()
    data = complete(body, transport=transport)
    raw = _strip_fences(_content_text(data))
    try:
        parsed = Extraction.model_validate_json(raw)
    except ValidationError as exc:
        # One repair pass: ask the same model to fix its own JSON against the schema.
        log.warning("extraction JSON invalid (%s); retrying once", str(exc)[:200])
        repair = dict(body)
        repair["messages"] = body["messages"] + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": f"That JSON did not validate: {str(exc)[:800]}. Return the corrected JSON only."},
        ]
        data2 = complete(repair, transport=transport)
        parsed = Extraction.model_validate_json(_strip_fences(_content_text(data2)))
        u2 = _usage(data2)
        u1 = _usage(data)
        data = data2
        data["usage"] = {"prompt_tokens": u1["input_tokens"] + u2["input_tokens"],
                         "completion_tokens": u1["output_tokens"] + u2["output_tokens"],
                         "cost": u1["cost_usd"] + u2["cost_usd"]}
    meta = {
        **_usage(data),
        "model": data.get("model") or model,
        "engine": engine if pdf_bytes is not None else ("image" if image is not None else "text"),
        "prompt_version": PROMPT_VERSION,
        "finish_reason": ((data.get("choices") or [{}])[0]).get("finish_reason") or "",
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return parsed, meta


def map_table(name: str, table: list[list[str]], *, model: str | None = None, effort: str | None = None,
              transport: Transport | None = None) -> tuple[TableMapping, dict[str, Any]]:
    """One call that returns how to read a large table; the rows themselves never go to the model."""
    from .tabular import SAMPLE_ROWS, column_summaries

    model = model or settings.model
    header = table[0] if table else []
    sample = table[: SAMPLE_ROWS + 1]
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": MAP_TABLE_SYSTEM, "cache_control": {"type": "ephemeral"}}]},
            {"role": "user", "content": [{"type": "text", "text": user_table_block(name, header, sample, column_summaries(table), len(table))}]},
        ],
        "response_format": {"type": "json_schema", "json_schema": {"name": "table_mapping", "strict": True, "schema": TableMapping.model_json_schema()}},
        "provider": {"require_parameters": True, "data_collection": "deny"},
        "reasoning": {"effort": effort or "low"},
        "usage": {"include": True},
        "max_tokens": 6000,
    }
    if settings.fallback_model and settings.fallback_model != model:
        body["models"] = [model, settings.fallback_model]
    started = time.perf_counter()
    data = complete(body, transport=transport)
    mp = TableMapping.model_validate_json(_strip_fences(_content_text(data)))
    meta = {**_usage(data), "model": data.get("model") or model, "engine": "table-mapping", "prompt_version": PROMPT_VERSION,
            "finish_reason": ((data.get("choices") or [{}])[0]).get("finish_reason") or "", "duration_ms": int((time.perf_counter() - started) * 1000)}
    return mp, meta
