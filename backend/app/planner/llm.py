from __future__ import annotations

import os
from collections.abc import Callable

import httpx
from app.planner.explanations import ExplanationService
from app.planner.service import Planner

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"


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
) -> Callable[[str], str] | None:
    """Return a Groq chat callable, or None when no key is configured."""

    _load_environment()
    key = (api_key or os.getenv("GROQ_API_KEY", "")).strip()
    if not key:
        return None
    chosen_model = model or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL

    def call(prompt: str) -> str:
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
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]

    return call


def build_explanation_service(llm: Callable[[str], str] | None = None) -> ExplanationService:
    return ExplanationService(llm if llm is not None else groq_llm())


def build_planner(llm: Callable[[str], str] | None = None) -> Planner:
    """Planner wired to Groq when GROQ_API_KEY is set, otherwise deterministic fallback."""

    return Planner(build_explanation_service(llm))
