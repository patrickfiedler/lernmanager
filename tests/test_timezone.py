"""Every timestamp the app stores uses one time basis: local wall clock.

Found 2026-08-27 in production: the UI showed 7:16 for an event that happened at
9:16, while the VPS clock itself was correct (CEST). Cause: SQLite's
CURRENT_TIMESTAMP is UTC unconditionally, so columns defaulting to it stored UTC
while the rest of the app wrote local time via datetime.now() -- two time bases in
one database, rendered verbatim by templates.

The rule these tests defend: writes go through models.now_local(), and any query
comparing against them uses models.local_cutoff(), never SQL-side datetime('now')
(which is UTC and would drift against the rows it is compared with).
"""
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from zoneinfo import ZoneInfo

import config
import models


def _offset_hours(stored, reference_utc):
    delta = datetime.strptime(stored, '%Y-%m-%d %H:%M:%S').replace(
        tzinfo=dt_timezone.utc) - reference_utc
    return round(delta.total_seconds() / 3600)


def test_now_local_is_ahead_of_utc_in_a_positive_offset_zone(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    expected = datetime.now(ZoneInfo("Europe/Berlin")).strftime('%Y-%m-%d %H')
    assert models.now_local().startswith(expected)


def test_now_local_does_not_depend_on_the_server_tz_env(monkeypatch):
    """The bug class this guards: a VPS rebuilt without TZ set."""
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    berlin = models.now_local()
    monkeypatch.setattr(config, "TIMEZONE", "UTC")
    utc = models.now_local()
    assert berlin != utc  # the config zone is what decides, not the process


def test_unknown_timezone_falls_back_instead_of_raising(monkeypatch):
    """A typo in TIMEZONE must not 500 every write path that logs something."""
    monkeypatch.setattr(config, "TIMEZONE", "Not/AZone")
    assert models.now_local()  # no exception, still a usable timestamp


def test_local_cutoff_shares_the_basis_of_now_local(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    now = datetime.strptime(models.now_local(), '%Y-%m-%d %H:%M:%S')
    cutoff = datetime.strptime(models.local_cutoff(hours=1), '%Y-%m-%d %H:%M:%S')
    assert timedelta(minutes=59) <= (now - cutoff) <= timedelta(minutes=61)


def test_llm_usage_is_written_on_the_local_clock(db, monkeypatch):
    """The row and the rate-limit window must agree; they used to both be UTC, and
    the danger in moving one is moving only one."""
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    student_id = models.create_student("Test", "Kind", "tzuser", "pw123")

    before_utc = datetime.now(dt_timezone.utc)
    models.record_llm_usage(student_id, 'llm_grading', 0)

    with models.db_session() as conn:
        stored = conn.execute(
            "SELECT timestamp FROM llm_usage WHERE student_id = ?", (student_id,)
        ).fetchone()['timestamp']

    assert _offset_hours(stored, before_utc) in (1, 2)  # CET or CEST, never 0


def test_rate_limit_still_counts_a_freshly_written_row(db, monkeypatch):
    """A local-time row compared against a UTC SQL window would look 2h old and
    fall outside it -- silently doubling every student's effective budget."""
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    monkeypatch.setattr(config, "LLM_MAX_CALLS_PER_STUDENT_PER_HOUR", 1)
    student_id = models.create_student("Test", "Kind", "tzuser2", "pw123")

    assert models.check_llm_rate_limit(student_id) is True
    models.record_llm_usage(student_id, 'llm_grading', 0)
    assert models.check_llm_rate_limit(student_id) is False


def test_checkpoint_answer_timestamp_is_local(db, monkeypatch):
    """The column that produced the visible 7:16-vs-9:16 report."""
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Berlin")
    student_id = models.create_student("Test", "Kind", "tzuser3", "pw123")
    task_id = models.create_task("T", "", "", "Chemie", "11", "")
    subtask_id = models.create_subtask(task_id, "### CP", reihenfolge=0)

    before_utc = datetime.now(dt_timezone.utc)
    models.create_checkpoint_answer(
        student_id, subtask_id, "sess-tz", question_index=0, attempt_no=1,
        answer_text="A", correct=True, feedback="ok", grader="llm",
        llm_model="m", hints_used_before=0, gave_up=False, prompt_version=None)

    with models.db_session() as conn:
        stored = conn.execute(
            "SELECT timestamp FROM checkpoint_answer WHERE student_id = ?",
            (student_id,)).fetchone()['timestamp']

    assert _offset_hours(stored, before_utc) in (1, 2)


def test_no_sql_string_still_uses_sqlite_current_timestamp():
    """CURRENT_TIMESTAMP is UTC; it must not reappear in a query.

    Checks executable string literals only, via ast -- docstrings and comments are
    excluded, because the explanation of this very bug names the thing it forbids
    and a plain text search would flag the documentation instead of the code.
    """
    import ast

    tree = ast.parse(open('models.py', encoding='utf-8').read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, 'body', None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    offenders = [
        node.value.splitlines()[0].strip()[:70]
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings and 'CURRENT_TIMESTAMP' in node.value
    ]
    assert not offenders, f"SQL reintroduced UTC clock: {offenders}"
