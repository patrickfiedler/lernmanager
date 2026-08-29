"""_judgment_confidence: read the grader's own certainty out of the logprobs.

The verdict rides on a single token inside {"correct": true, "feedback": "..."}. These
tests pin the two things that make finding it non-trivial: the key may be tokenised any
number of ways, and "true"/"false" also occur in the feedback text.

Everything here is instrumentation for a threshold nobody has set yet (migrate_052), so
every malformed shape must yield None rather than raise -- a student's grade must never
depend on whether a provider returned logprobs.
"""
import math

import llm_grading


class _Entry:
    def __init__(self, token, logprob=None):
        self.token = token
        self.logprob = logprob


class _Logprobs:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.logprobs = _Logprobs(content) if content is not None else None


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def _tokens(pairs):
    """pairs: [(token_text, logprob|None), ...] -- logprob None where it is irrelevant."""
    return _Response([_Entry(t, lp) for t, lp in pairs])


P90 = math.log(0.9)


def test_reads_the_verdict_token_probability():
    response = _tokens([('{"', None), ('correct', None), ('":', None),
                        ('true', P90), (',', None)])
    assert llm_grading._judgment_confidence(response) == 0.9


def test_key_and_value_fused_into_one_token():
    """`"correct":true` as a single token still resolves -- the offset lands inside it."""
    response = _tokens([('{', None), ('"correct":true', P90), (',', None)])
    assert llm_grading._judgment_confidence(response) == 0.9


def test_leading_space_before_the_value():
    response = _tokens([('{"correct":', None), (' false', P90), ('}', None)])
    assert llm_grading._judgment_confidence(response) == 0.9


def test_true_inside_the_feedback_is_not_mistaken_for_the_verdict():
    """The trap this function exists to avoid: matching the first boolean-looking token
    anywhere would report a word from the explanation as the grader's certainty."""
    response = _tokens([('{"correct":', None), ('false', P90), (', "feedback": "', None),
                        ('true', math.log(0.1)), ('"}', None)])
    assert llm_grading._judgment_confidence(response) == 0.9


def test_probability_is_clamped_to_one():
    """exp(0.0) can float a hair past 1.0; a threshold read off that would be nonsense."""
    response = _tokens([('{"correct":', None), ('true', 0.0), ('}', None)])
    assert llm_grading._judgment_confidence(response) == 1.0


def test_no_logprobs_returns_none():
    assert llm_grading._judgment_confidence(_Response(None)) is None


def test_empty_content_returns_none():
    assert llm_grading._judgment_confidence(_Response([])) is None


def test_missing_key_returns_none():
    response = _tokens([('{"', None), ('verdict', None), ('":', None), ('true', P90)])
    assert llm_grading._judgment_confidence(response) is None


def test_truncated_after_the_key_returns_none():
    """Key present, value never emitted -- must not report the colon's confidence."""
    response = _tokens([('{"correct"', None), (':', P90)])
    assert llm_grading._judgment_confidence(response) is None


def test_missing_logprob_on_the_verdict_token_returns_none():
    response = _tokens([('{"correct":', None), ('true', None), ('}', None)])
    assert llm_grading._judgment_confidence(response) is None


def test_entry_without_a_token_attribute_returns_none():
    class _Bare:
        logprob = P90

    assert llm_grading._judgment_confidence(_Response([_Bare()])) is None


def test_response_without_choices_returns_none():
    class _Empty:
        choices = []

    assert llm_grading._judgment_confidence(_Empty()) is None
