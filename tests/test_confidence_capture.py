"""Confidence capture must be free: it may cost data, never a grade (migrate_052).

Two things are pinned here. Checkpoints ask for logprobs and nothing else does -- warm-up
and practice would pay the overhead for a number no one reads. And a provider that
rejects the parameter gets a retry without it rather than taking grading down: LLM_MODEL
is a swappable .env knob and the endpoint answers unknown arguments with HTTP 400, which
is exactly how the reasoning_effort regression broke every call (test_llm_reasoning_kwargs).
"""
import math

import httpx
import pytest
from openai import APITimeoutError, BadRequestError

import config
import llm_grading


def _bad_request(message):
    """The real 400 an endpoint returns for an argument it does not know."""
    return BadRequestError(message, response=httpx.Response(
        400, request=httpx.Request("POST", "http://test")), body=None)


def _timeout():
    return APITimeoutError(request=httpx.Request("POST", "http://test"))


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)
        self.logprobs = None


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


VERDICT = '{"correct": true, "feedback": "Passt."}'


class _FakeClient:
    """Records the kwargs of every create() call; optionally fails the logprobs one.

    fail_with_logprobs takes the exception to raise, because "rejected" (400) and
    "too slow" (timeout) are opposite conditions that _call_llm must not conflate:
    one is permanent and worth remembering, the other costs the student a second wait.
    """

    def __init__(self, fail_with_logprobs=None):
        self.calls = []
        self.fail_with_logprobs = fail_with_logprobs
        self.chat = self
        self.completions = self

    # _call_llm pins max_retries per call so the SDK cannot silently repeat a
    # timed-out request; the double mirrors the real copy-with-options.
    def with_options(self, **kwargs):
        self.options = kwargs
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_with_logprobs is not None and 'logprobs' in kwargs:
            raise self.fail_with_logprobs
        return _Response(VERDICT)


def _patch(monkeypatch, client):
    monkeypatch.setattr(llm_grading, '_get_client', lambda: client)
    monkeypatch.setattr(config, 'LLM_MODEL', 'Meta-Llama-3.3-70B-Instruct')
    # A 400 is remembered process-wide on purpose; without this reset the first test
    # to see one would silently switch off the probe for every test after it.
    monkeypatch.setattr(llm_grading, '_logprobs_unsupported', False)


def test_checkpoint_call_requests_logprobs(monkeypatch):
    client = _FakeClient()
    _patch(monkeypatch, client)
    llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert client.calls[0]['logprobs'] is True
    # OVH accepts logprobs only with top_logprobs <= 1.
    assert client.calls[0]['top_logprobs'] == 1


def test_practice_call_does_not_request_logprobs(monkeypatch):
    client = _FakeClient()
    _patch(monkeypatch, client)
    llm_grading._call_llm('F', 'R', 'A')
    assert 'logprobs' not in client.calls[0]


def test_rejected_logprobs_retries_without_and_still_grades(monkeypatch):
    """The whole point: losing confidence must degrade to "less data", not "no grade"."""
    client = _FakeClient(fail_with_logprobs=_bad_request("logprobs not supported"))
    _patch(monkeypatch, client)
    result = llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert result['correct'] is True
    assert result['confidence'] is None
    assert len(client.calls) == 2
    assert 'logprobs' not in client.calls[1]


def test_rejection_is_remembered_so_it_is_probed_once(monkeypatch):
    """A 400 is a property of the endpoint, not of one answer.

    Re-probing would spend a whole grading budget per student to relearn the same no.
    """
    client = _FakeClient(fail_with_logprobs=_bad_request("logprobs not supported"))
    _patch(monkeypatch, client)
    llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert sum('logprobs' in c for c in client.calls) == 1
    assert len(client.calls) == 3   # probe + its retry, then straight to plain


def test_timeout_retries_once_within_the_same_budget(monkeypatch):
    """Regression (2026-09-07): a timeout must not buy a second full budget.

    timeout= applies per attempt, so a fresh 15s for the retry turned a 15s promise
    into a 30s+ wait -- on top of the SDK's own silent retries. The student is already
    waiting when the retry starts, so it gets what is LEFT, never a new budget.
    """
    client = _FakeClient(fail_with_logprobs=_timeout())
    _patch(monkeypatch, client)
    result = llm_grading._call_llm('F', 'R', 'A', timeout=15, want_confidence=True)
    assert result['correct'] is True
    assert result['confidence'] is None
    assert len(client.calls) == 2
    assert 'logprobs' not in client.calls[1]
    assert client.calls[1]['timeout'] <= client.calls[0]['timeout']


def test_timeout_is_not_remembered(monkeypatch):
    """Slow once is not unsupported: the next answer must still ask for confidence."""
    client = _FakeClient(fail_with_logprobs=_timeout())
    _patch(monkeypatch, client)
    llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert sum('logprobs' in c for c in client.calls) == 2


def test_sdk_retries_are_capped(monkeypatch):
    """timeout= is per attempt: with the SDK's default 2 retries a 15s budget is 45s."""
    client = _FakeClient()
    _patch(monkeypatch, client)
    llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert client.options['max_retries'] == 0


def test_confidence_is_none_when_provider_returns_no_logprobs(monkeypatch):
    client = _FakeClient()
    _patch(monkeypatch, client)
    assert llm_grading._call_llm('F', 'R', 'A', want_confidence=True)['confidence'] is None


def test_extraction_failure_does_not_break_grading(monkeypatch):
    """_judgment_confidence is wrapped: instrumentation may not throw away a verdict."""
    client = _FakeClient()
    _patch(monkeypatch, client)

    def _boom(response):
        raise ValueError('unexpected logprobs shape')

    monkeypatch.setattr(llm_grading, '_judgment_confidence', _boom)
    result = llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert result['correct'] is True
    assert result['confidence'] is None


def test_confidence_reaches_the_caller(monkeypatch):
    client = _FakeClient()
    _patch(monkeypatch, client)
    monkeypatch.setattr(llm_grading, '_judgment_confidence', lambda response: 0.73)
    assert llm_grading._call_llm('F', 'R', 'A', want_confidence=True)['confidence'] == 0.73
