"""Regression: reasoning_effort must only be sent to models that support it.

Found 2026-08-13: reasoning_effort="none" was sent unconditionally on every
chat.completions.create() call. Required for reasoning models (Qwen3.6 spends its
whole token budget on internal reasoning otherwise) but rejected outright (HTTP 400)
by non-reasoning models like Meta-Llama-3.3-70B-Instruct. Since LLM_MODEL is a
swappable .env knob, this broke every grading call whenever it pointed at a
non-reasoning model.
"""
import config
import llm_grading


def test_reasoning_model_gets_reasoning_effort(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "Qwen3.6-27B")
    assert llm_grading._reasoning_kwargs() == {"reasoning_effort": "none"}


def test_non_reasoning_model_gets_no_kwargs(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "Meta-Llama-3.3-70B-Instruct")
    assert llm_grading._reasoning_kwargs() == {}


def test_mistral_gets_no_kwargs(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "Mistral-Nemo-Instruct-2407")
    assert llm_grading._reasoning_kwargs() == {}


def test_deepseek_r1_gets_reasoning_effort(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "deepseek-r1-distill-llama-70b")
    assert llm_grading._reasoning_kwargs() == {"reasoning_effort": "none"}
