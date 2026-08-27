"""Regression: checkpoint grading must use its own, longer LLM timeout.

Found 2026-08-27: checkpoint_quiz answers were graded with config.LLM_TIMEOUT (5s),
the budget sized for short formative-practice answers, even though checkpoint
answers are multi-sentence explanations judged against the stricter prompt. Unlike a
practice retry, a timeout there returns None under strict=True and costs the student
an attempt, so the two budgets must stay separately tunable.
"""
import config
import llm_grading
import pytest


@pytest.fixture
def captured(monkeypatch):
    """Capture the kwargs of the chat.completions.create() call."""
    seen = {}

    class _Completions:
        def create(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop after capturing")

    class _Client:
        chat = type("chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(llm_grading, "_get_client", lambda: _Client())
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(llm_grading.models, "check_llm_rate_limit", lambda *a, **k: True)
    return seen


def _grade(usage_tag):
    return llm_grading.grade_answer("Frage?", "Rubrik", "Antwort", student_id=1,
                                    usage_tag=usage_tag)


def test_checkpoint_uses_checkpoint_timeout(captured, monkeypatch):
    monkeypatch.setattr(config, "LLM_CHECKPOINT_TIMEOUT", 15)
    _grade("checkpoint_quiz")
    assert captured["timeout"] == 15


def test_regular_quiz_still_uses_short_timeout(captured, monkeypatch):
    monkeypatch.setattr(config, "LLM_TIMEOUT", 5)
    _grade("llm_grading")
    assert captured["timeout"] == 5


def test_checkpoint_timeout_is_env_tunable(captured, monkeypatch):
    monkeypatch.setattr(config, "LLM_CHECKPOINT_TIMEOUT", 42)
    _grade("checkpoint_quiz")
    assert captured["timeout"] == 42


def test_checkpoint_still_gets_the_stricter_prompt(captured):
    """The timeout split must not disturb the prompt split it sits next to."""
    _grade("checkpoint_quiz")
    assert captured["messages"][0]["content"] == llm_grading.CHECKPOINT_SYSTEM_PROMPT
