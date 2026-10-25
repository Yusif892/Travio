from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx
from app.planner.explanations import ExplanationService
from app.planner.service import Planner

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 0.5


class LLMError(RuntimeError):
    """Raised when the LLM provider fails or returns an unusable response."""


def _load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def groq_llm(
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 30.0,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> Callable[[str], str] | None:
    """Return a Groq chat callable, or None when no key is configured.

    Transient failures (timeouts, transport errors, HTTP 429/5xx) are retried with
    exponential backoff. Malformed provider responses raise ``LLMError`` and never
    leak the API key.
    """

    _load_environment()
    key = (api_key or os.getenv("GROQ_API_KEY", "")).strip()
    if not key:
        return None
    chosen_model = model or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL
    retries = max(int(max_retries), 0)
    backoff = max(float(backoff_seconds), 0.0)

    def call(prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMError("Prompt must be a non-empty string")

        last_error: LLMError | None = None
        for attempt in range(retries + 1):
            try:
                response = httpx.post(
                    GROQ_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": chosen_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = LLMError(f"Groq request failed ({type(exc).__name__})")
            else:
                status = response.status_code
                if status == 429 or status >= 500:
                    last_error = LLMError(f"Groq returned HTTP {status}")
                else:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError:
                        raise LLMError(
                            f"Groq rejected the request with HTTP {status}"
                        ) from None
                    try:
                        payload = response.json()
                    except ValueError:
                        raise LLMError("Groq returned invalid JSON") from None
                    try:
                        content = payload["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        raise LLMError("Groq returned an unexpected response shape") from None
                    if not isinstance(content, str) or not content.strip():
                        raise LLMError("Groq returned an empty response")
                    return content

            if attempt < retries:
                time.sleep(backoff * (2**attempt))

        raise last_error or LLMError("Groq request failed")

    return call


def build_explanation_service(llm: Callable[[str], str] | None = None) -> ExplanationService:
    return ExplanationService(llm if llm is not None else groq_llm())


def build_planner(llm: Callable[[str], str] | None = None) -> Planner:
    """Planner wired to Groq when GROQ_API_KEY is set, otherwise deterministic fallback."""

    return Planner(build_explanation_service(llm))
