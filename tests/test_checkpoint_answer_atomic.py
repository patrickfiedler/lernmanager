"""The answer log numbers and de-duplicates itself, under the write lock.

Patrick, 2026-09-06, from chemie's findings 1 and 2 on the 2026-09-06 export.

Two separate symptoms, one cause: the route's attempt counter lives in the Flask
session cookie, which two overlapping requests both read before either writes. So
they stamped the same attempt_no (chemie saw eight rows all carrying 1), and the
2026-09-04 unchanged-answer guard could not stop the second row being written --
that guard reads in its own transaction, then a grading call takes seconds, and
only then does the insert happen.

Both fixes belong in the same place: derive attempt_no as MAX+1 and re-check for
an identical graded row inside the SAME transaction as the insert. SQLite
serialises writers, so the second caller finds the first caller's row.
"""
import json

import pytest

import models

QUIZ = {"questions": [{"type": "short_answer", "text": "Erkläre.", "rubric": "Kern."}]}


@pytest.fixture
def ids(db):
    """Real student and checkpoint rows -- checkpoint_answer has foreign keys."""
    student_id = models.create_student("Muster", "Kaya", "happypanda", "bacado42")
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint", reihenfolge=0, quiz_json=json.dumps(QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern")
    return student_id, subtask_id


@pytest.fixture
def log(ids):
    student_id, subtask_id = ids

    def _log(session_uid="s1", question_index=0, text="Antwort", correct=True,
             attempt_no=None, dedupe=False):
        return models.create_checkpoint_answer(
            student_id=student_id, checkpoint_id=subtask_id, session_uid=session_uid,
            question_index=question_index, attempt_no=attempt_no, answer_text=text,
            correct=correct, feedback="fb", grader="exact", dedupe=dedupe)

    return _log


def test_attempt_no_is_derived_from_the_log_not_the_caller(log):
    """MAX+1 per (session, question) -- the number no cookie can lose."""
    assert log(text="eins")["attempt_no"] == 1
    assert log(text="zwei")["attempt_no"] == 2
    assert log(text="drei")["attempt_no"] == 3
    # A different question numbers independently.
    assert log(question_index=1, text="eins")["attempt_no"] == 1


def test_dedupe_suppresses_an_identical_graded_resubmission(log):
    first = log(text="Berlin", dedupe=True)
    second = log(text="  BERLIN  ", dedupe=True)   # normalised: same answer

    assert first["created"] is True
    assert second["created"] is False, "identical text must not add a second row"
    assert second["existing"]["feedback"] == "fb"

    with models.db_session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM checkpoint_answer WHERE session_uid = 's1'"
        ).fetchone()[0]
    assert count == 1


def test_dedupe_lets_a_changed_answer_through(log):
    log(text="Neutron", correct=False, dedupe=True)
    changed = log(text="Neutronen", correct=True, dedupe=True)
    assert changed["created"] is True, "a typo fix is a real retry, not a duplicate"
    assert changed["attempt_no"] == 2


def test_dedupe_does_not_swallow_a_retry_after_a_grading_failure(log):
    """correct IS NULL means the LLM failed and the student was TOLD to retry.
    Resending the same text is that retry, not a duplicate."""
    log(text="Berlin", correct=None, dedupe=True)
    retry = log(text="Berlin", correct=True, dedupe=True)
    assert retry["created"] is True
    assert retry["attempt_no"] == 2


def test_dedupe_is_off_by_default(log):
    """Give-up and report rows go through the same insert and must never be
    collapsed into a preceding answer."""
    log(text="Berlin")
    again = log(text="Berlin")
    assert again["created"] is True
    assert again["attempt_no"] == 2
