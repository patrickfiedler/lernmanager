"""Regression: the browser must never give up before the server is done.

Found 2026-09-07 from production logs. On 2026-08-27 LLM_CHECKPOINT_TIMEOUT was raised
5s -> 15s (commit 1489673). The browser's window lived in static/js/llm_button.js as a
hardcoded 15000, was not raised with it, and nothing failed -- the two numbers simply
became equal, so both expired at the same instant. Chemie students then got "Das dauert
gerade zu lange" on checkpoint answers the server graded and stored a second later
(20 occurrences across 2026-09-02 and 2026-09-07).

Nothing here checks a timeout value for being "right". What is pinned is the
RELATIONSHIP -- client window strictly greater than the server's worst case -- and that
the client reads the number instead of carrying its own copy. A duplicated constant is
what broke; a test that only asserted "== 15000" would have passed all the way through.
"""
import re
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent.parent
LLM_BUTTON_JS = ROOT / 'static' / 'js' / 'llm_button.js'
BASE_HTML = ROOT / 'templates' / 'base.html'


def _server_worst_case_seconds():
    """Longest a graded call may legitimately take: one full budget, then the
    shortened retry _call_llm allows after a logprobs timeout."""
    return config.LLM_CHECKPOINT_TIMEOUT + config.LLM_RETRY_FLOOR


def test_client_window_outlasts_the_server():
    """The whole bug in one assertion."""
    assert config.LLM_CLIENT_TIMEOUT_MS / 1000 > _server_worst_case_seconds()


def test_client_window_has_real_margin():
    """Equal-but-for-a-millisecond would pass the test above and still race.

    The margin covers request/response transfer and a loaded server -- the window has
    to outlast the server by enough to be useful, not merely by arithmetic.
    """
    slack = config.LLM_CLIENT_TIMEOUT_MS / 1000 - _server_worst_case_seconds()
    assert slack >= 3


def test_client_window_is_not_absurd():
    """A window far past the server's worst case stops being a safety net and just
    parks a child in front of a spinner for a request that will never answer."""
    assert config.LLM_CLIENT_TIMEOUT_MS / 1000 <= _server_worst_case_seconds() * 3


def test_js_reads_the_timeout_from_the_server():
    """The fix is that the number has ONE home. A second copy in JS is the bug."""
    source = LLM_BUTTON_JS.read_text(encoding='utf-8')
    assert 'meta[name="llm-timeout-ms"]' in source

    # No bare 15000 anywhere: that literal was the stale copy of a server budget.
    assert '15000' not in source


def test_base_template_emits_the_meta_tag():
    """The JS falls back silently when the tag is missing, so its absence would
    reintroduce a hardcoded window without any error."""
    assert 'llm-timeout-ms' in BASE_HTML.read_text(encoding='utf-8')


def test_js_fallback_still_outlasts_the_server():
    """A page rendered without the meta tag must not land back in the racing state."""
    source = LLM_BUTTON_JS.read_text(encoding='utf-8')
    match = re.search(r"parseInt\(META_TIMEOUT\.content, 10\)\) \|\| (\d+)", source)
    assert match, "fallback literal not found -- update this test with the code"
    assert int(match.group(1)) / 1000 > _server_worst_case_seconds()
