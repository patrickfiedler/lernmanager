"""Regression: the OpenAI client must be reused across calls, not rebuilt each time.

Found 2026-08-27: _get_client() constructed a new OpenAI() on every grading call,
so every call opened a fresh httpx connection pool -- a new TCP + TLS handshake to
the provider, paid out of the same 5s LLM_TIMEOUT the model has to answer in.

The cache is keyed on (LLM_BASE_URL, LLM_API_KEY) rather than a bare global,
because those are swappable .env knobs that tests monkeypatch at runtime; a plain
singleton would keep serving the old endpoint after such a change.
"""
import config
import llm_grading
import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    llm_grading._client_cache.clear()
    yield
    llm_grading._client_cache.clear()


def test_same_config_reuses_one_client(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "key-a")
    assert llm_grading._get_client() is llm_grading._get_client()


def test_changed_base_url_builds_a_new_client(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://a.invalid/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "key-a")
    first = llm_grading._get_client()

    monkeypatch.setattr(config, "LLM_BASE_URL", "https://b.invalid/v1")
    second = llm_grading._get_client()
    assert first is not second
    assert str(second.base_url).startswith("https://b.invalid")


def test_changed_api_key_builds_a_new_client(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://a.invalid/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "key-a")
    first = llm_grading._get_client()

    monkeypatch.setattr(config, "LLM_API_KEY", "key-b")
    assert llm_grading._get_client() is not first


def test_missing_base_url_still_raises(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", None)
    with pytest.raises(ValueError):
        llm_grading._get_client()
