from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import time


@dataclass(frozen=True)
class VolcConfig:
    api_key: str
    base_url: str
    model: str


class VolcengineError(RuntimeError):
    pass


def load_volc_config() -> VolcConfig | None:
    api_key = os.environ.get("VOLC_API_KEY", "").strip()
    model = os.environ.get("VOLC_MODEL", "").strip()
    base_url = os.environ.get("VOLC_BASE_URL", "https://ark.cn-beijing.volces.com").strip()
    if not api_key or not model:
        return None
    return VolcConfig(api_key=api_key, base_url=base_url, model=model)


def _read_prompt(rel_path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    p = root / rel_path
    return p.read_text(encoding="utf-8")


def volc_chat_json(config: VolcConfig, user_text: str, timeout_s: float = 12.0) -> dict:
    """
    Minimal Ark-compatible chat completions call.
    We keep it flexible: base_url/model are env-configured.
    """
    system_prompt = _read_prompt("prompts/moderation_system.txt")
    url = f"{config.base_url.rstrip('/')}/api/v3/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.1,
    }

    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise VolcengineError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise VolcengineError(f"Unexpected response shape: {json.dumps(data)[:800]}") from e

    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # Some models wrap JSON in text; try to extract the first {...}
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise VolcengineError(f"Model did not return valid JSON: {content[:500]}") from e


@dataclass(frozen=True)
class VolcCallTrace:
    model: str
    ok: bool
    http_status: int | None
    latency_ms: int | None
    error: str | None
    response_json: str


def volc_chat_json_traced(
    config: VolcConfig, user_text: str, timeout_s: float = 12.0
) -> tuple[dict, VolcCallTrace] | tuple[None, VolcCallTrace]:
    system_prompt = _read_prompt("prompts/moderation_system.txt")
    url = f"{config.base_url.rstrip('/')}/api/v3/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.1,
    }

    t0 = time.perf_counter()
    with httpx.Client(timeout=timeout_s) as client:
        try:
            resp = client.post(url, headers=headers, json=payload)
        except Exception as e:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - t0) * 1000)
            err = f"{type(e).__name__}: {e}"[:500]
            trace = VolcCallTrace(
                model=config.model,
                ok=False,
                http_status=None,
                latency_ms=latency_ms,
                error=err,
                response_json="",
            )
            return None, trace

        latency_ms = int((time.perf_counter() - t0) * 1000)
        http_status = resp.status_code
        if resp.status_code >= 400:
            trace = VolcCallTrace(
                model=config.model,
                ok=False,
                http_status=http_status,
                latency_ms=latency_ms,
                error=resp.text[:500],
                response_json=resp.text[:2000],
            )
            return None, trace

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            trace = VolcCallTrace(
                model=config.model,
                ok=False,
                http_status=http_status,
                latency_ms=latency_ms,
                error=f"Invalid JSON response: {e}"[:500],
                response_json=resp.text[:2000],
            )
            return None, trace

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001
            trace = VolcCallTrace(
                model=config.model,
                ok=False,
                http_status=http_status,
                latency_ms=latency_ms,
                error=f"Unexpected response shape: {e}"[:500],
                response_json=json.dumps(data, ensure_ascii=False)[:2000],
            )
            return None, trace

        content = str(content).strip()
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(content[start : end + 1])
                except json.JSONDecodeError as e2:
                    trace = VolcCallTrace(
                        model=config.model,
                        ok=False,
                        http_status=http_status,
                        latency_ms=latency_ms,
                        error=f"Model did not return valid JSON: {e2}"[:500],
                        response_json=content[:2000],
                    )
                    return None, trace
            else:
                trace = VolcCallTrace(
                    model=config.model,
                    ok=False,
                    http_status=http_status,
                    latency_ms=latency_ms,
                    error="Model did not return valid JSON"[:500],
                    response_json=content[:2000],
                )
                return None, trace

        trace = VolcCallTrace(
            model=config.model,
            ok=True,
            http_status=http_status,
            latency_ms=latency_ms,
            error=None,
            response_json=json.dumps(parsed, ensure_ascii=False)[:2000],
        )
        return parsed, trace


def volc_chat_text_traced(
    config: VolcConfig, system_prompt: str, user_text: str, timeout_s: float = 12.0
) -> tuple[str | None, VolcCallTrace]:
    """
    Chat completions call that returns plain text (no JSON parsing).
    Used for translation / rewrite suggestion.
    """
    url = f"{config.base_url.rstrip('/')}/api/v3/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.1,
    }

    t0 = time.perf_counter()
    with httpx.Client(timeout=timeout_s) as client:
        try:
            resp = client.post(url, headers=headers, json=payload)
        except Exception as e:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - t0) * 1000)
            err = f"{type(e).__name__}: {e}"[:500]
            return (
                None,
                VolcCallTrace(
                    model=config.model,
                    ok=False,
                    http_status=None,
                    latency_ms=latency_ms,
                    error=err,
                    response_json="",
                ),
            )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        http_status = resp.status_code
        if resp.status_code >= 400:
            return (
                None,
                VolcCallTrace(
                    model=config.model,
                    ok=False,
                    http_status=http_status,
                    latency_ms=latency_ms,
                    error=resp.text[:500],
                    response_json=resp.text[:2000],
                ),
            )

        try:
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            return (
                None,
                VolcCallTrace(
                    model=config.model,
                    ok=False,
                    http_status=http_status,
                    latency_ms=latency_ms,
                    error=f"Invalid JSON response: {e}"[:500],
                    response_json=resp.text[:2000],
                ),
            )

        try:
            content = str(data["choices"][0]["message"]["content"]).strip()
        except Exception as e:  # noqa: BLE001
            return (
                None,
                VolcCallTrace(
                    model=config.model,
                    ok=False,
                    http_status=http_status,
                    latency_ms=latency_ms,
                    error=f"Unexpected response shape: {e}"[:500],
                    response_json=json.dumps(data, ensure_ascii=False)[:2000],
                ),
            )

        ok = bool(content)
        return (
            content if ok else None,
            VolcCallTrace(
                model=config.model,
                ok=ok,
                http_status=http_status,
                latency_ms=latency_ms,
                error=None if ok else "empty_content",
                response_json=content[:2000],
            ),
        )

