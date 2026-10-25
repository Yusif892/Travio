from __future__ import annotations

import app.planner.llm as llm_module
from app.planner.llm import build_planner, groq_llm

from tests.factories import make_planning


def _disable_dotenv(monkeypatch) -> None:
    monkeypatch.setattr(llm_module, "_load_environment", lambda: None)


def test_groq_returns_none_without_a_key(monkeypatch):
    _disable_dotenv(monkeypatch)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert groq_llm() is None


def test_groq_reads_the_environment_key(monkeypatch):
    _disable_dotenv(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    assert callable(groq_llm())


def test_build_planner_works_without_a_key(monkeypatch):
    _disable_dotenv(monkeypatch)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    plan = build_planner().plan(make_planning())
    assert plan.days
    assert plan.explanations
