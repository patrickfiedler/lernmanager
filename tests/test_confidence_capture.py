"""Confidence capture must be free: it may cost data, never a grade (migrate_052).

Two things are pinned here. Checkpoints ask for logprobs and nothing else does -- warm-up
and practice would pay the overhead for a number no one reads. And a provider that
rejects the parameter gets a retry without it rather than taking grading down: LLM_MODEL
is a swappable .env knob and the endpoint answers unknown arguments with HTTP 400, which
is exactly how the reasoning_effort regression broke every call (test_llm_reasoning_kwargs).
"""
import math

import config
import llm_grading


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
    """Records the kwargs of every create() call; optionally fails the first one."""

    def __init__(self, fail_with_logprobs=False):
        self.calls = []
        self.fail_with_logprobs = fail_with_logprobs
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_with_logprobs and 'logprobs' in kwargs:
            raise RuntimeError("400 feature 'logprobs' is not currently supported")
        return _Response(VERDICT)


def _patch(monkeypatch, client):
    monkeypatch.setattr(llm_grading, '_get_client', lambda: client)
    monkeypatch.setattr(config, 'LLM_MODEL', 'Meta-Llama-3.3-70B-Instruct')


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
    client = _FakeClient(fail_with_logprobs=True)
    _patch(monkeypatch, client)
    result = llm_grading._call_llm('F', 'R', 'A', want_confidence=True)
    assert result['correct'] is True
    assert result['confidence'] is None
    assert len(client.calls) == 2
    assert 'logprobs' not in client.calls[1]


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
