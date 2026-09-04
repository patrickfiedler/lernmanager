"""Resubmitting an unchanged answer must not be regraded.

Patrick, 2026-09-04. The solved-question guard in student_checkpoint_answer only
ever covered a question the student had already got right. An unchanged WRONG
answer fell straight through it and was graded again on every click: on 2026-09-02
that was 47 of the day's resubmissions (17 within 15s of each other, 30 later).

It costs no points -- the per-question ladder is 3 -> 2 -> 2 -> 2, so the first
wrong attempt already did the damage -- but it spends an LLM call per click and
puts a duplicate row in front of the teacher in the review UI.

The rule is exact match after normalising, NOT the fuzzy 0.95 similarity
_is_duplicate_submission uses to detect double-clicks after the fact. That rule is
safe only because it also requires both verdicts to agree, which is unknowable
before grading.
"""
import json

import pytest

import llm_grading
import models

QUIZ = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"type": "fill_blank", "text": "Die Hauptstadt ist ___.", "answers": ["Berlin"]},
    ]
}


@pytest.fixture
def graded_wrong(monkeypatch):
    """Stub the LLM so a non-matching fill_blank comes back as a real verdict.

    Without this the fixture's LLM_ENABLED=False turns every fallback into a 503
    (strict=True -> correct is None), which is a different code path from the one
    under test. Counts its calls so a test can assert the guard actually prevented
    the second grading rather than merely hiding its result.
    """
    calls = []

    def fake_grade_answer(question, expected, student_answer, *a, **k):
        calls.append(student_answer)
        return {"correct": False, "feedback": "Nicht richtig.", "source": "llm"}

    monkeypatch.setattr(llm_grading, "grade_answer", fake_grade_answer)
    return calls


def _checkpoint_student(app, quiz=QUIZ):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "unchangedtest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(quiz), checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def _answer(client, subtask_id, answer, question_index=0):
    return client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": question_index, "answer": answer,
    }).get_json()


def _logged(subtask_id, question_index=0):
    with models.db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM checkpoint_answer WHERE checkpoint_id = ? AND question_index = ?"
            " ORDER BY id", (subtask_id, question_index)).fetchall()]


def test_identical_wrong_answer_is_not_regraded(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    first = _answer(client, subtask_id, [1])
    assert first["correct"] is False
    assert first["attempts"] == 1

    second = _answer(client, subtask_id, [1])
    assert second["unchanged"] is True
    assert second["correct"] is False       # same verdict handed back
    assert second["attempts"] == 1          # and no attempt burned

    # The point of the guard: one row, not two, for the teacher to read.
    assert len(_logged(subtask_id)) == 1


def test_changed_answer_is_graded_normally(app, client):
    """The guard must not swallow a genuine second try."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    assert _answer(client, subtask_id, [1])["correct"] is False
    second = _answer(client, subtask_id, [0])
    assert second.get("unchanged") is None
    assert second["correct"] is True
    assert second["attempts"] == 2
    assert len(_logged(subtask_id)) == 2


def test_whitespace_and_case_count_as_unchanged(app, client, graded_wrong):
    """_normalized_answer_text lowercases and collapses whitespace, so retyping the
    same words differently spaced is still the same answer."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    first = _answer(client, subtask_id, "Paris", question_index=1)
    assert first["correct"] is False

    again = _answer(client, subtask_id, "  paris  ", question_index=1)
    assert again["unchanged"] is True
    assert len(_logged(subtask_id, question_index=1)) == 1
    assert len(graded_wrong) == 1           # the LLM was called once, not twice


def test_near_miss_typo_fix_is_still_graded(app, client, graded_wrong):
    """The deliberate difference from _is_duplicate_submission's 0.95 fuzzy rule:
    a one-character correction is a real retry and must reach the grader."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    assert _answer(client, subtask_id, "Berlim", question_index=1)["correct"] is False
    # "Berlin" matches the answer key outright, so it never reaches the LLM -- which
    # is the point: the guard let it through to grading at all.
    fixed = _answer(client, subtask_id, "Berlin", question_index=1)
    assert fixed.get("unchanged") is None
    assert fixed["correct"] is True
    assert len(_logged(subtask_id, question_index=1)) == 2


def test_solved_guard_still_wins(app, client):
    """A solved question keeps answering via the older, cheaper guard -- which
    reports `duplicate`, not `unchanged`."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    assert _answer(client, subtask_id, [0])["correct"] is True
    again = _answer(client, subtask_id, [0])
    assert again["duplicate"] is True
    assert again["correct"] is True
    assert len(_logged(subtask_id)) == 1


def test_ungraded_previous_answer_does_not_block_a_retry(app, client, monkeypatch):
    """correct IS NULL means the LLM failed, and its own error message tells the
    student to try again. Resending the same text is then the retry we asked for,
    so the guard must stay out of the way.

    Drives the real outage path rather than hand-writing the row: grade_answer
    returning None is exactly what llm_grading does under strict=True when grading
    could not happen, and it is what leaves correct NULL in the log.
    """
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    monkeypatch.setattr(llm_grading, "grade_answer", lambda *a, **k: None)
    down = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": 1, "answer": "Paris"})
    assert down.status_code == 503
    logged = _logged(subtask_id, question_index=1)
    assert len(logged) == 1 and logged[0]["correct"] is None

    # LLM is back. The same text must now reach the grader instead of being handed
    # the previous non-verdict.
    monkeypatch.setattr(llm_grading, "grade_answer",
                        lambda *a, **k: {"correct": False, "feedback": "Nein.", "source": "llm"})
    retry = _answer(client, subtask_id, "Paris", question_index=1)
    assert retry.get("unchanged") is None
    assert retry["correct"] is False        # actually graded this time
    assert len(_logged(subtask_id, question_index=1)) == 2
