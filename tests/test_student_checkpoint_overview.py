"""The student's own list of checkpoints and points.

Patrick, 2026-09-06. The score and its one-line reason are shown once, on the screen
that ends a session (chemie's agreed Option 1, chemie-checkpoint-status.md § 1).
After that a student had no way back to any of it -- not the number, not that a
report of theirs was rejected and now owes a redo. This page is the only place the
whole picture exists.

Read-only by construction: it opens nothing and changes no score.
"""
import json

import pytest

import models

QUIZ = {"questions": [{"type": "short_answer", "text": "Erkläre.", "rubric": "Kern."}]}

URL = "/schueler/checkpoints"


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Muster", "Kaya", "cpview", "bacado42")
    klasse_id = models.create_klasse("11c")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    plain = models.create_subtask(task_id, "### Normale Aufgabe", reihenfolge=0)
    cp = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=1, quiz_json=json.dumps(QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return {"student_id": student_id, "klasse_id": klasse_id, "task_id": task_id,
            "checkpoint_id": cp, "plain": plain}


def _get(client, data):
    with client.session_transaction() as sess:
        sess["student_id"] = data["student_id"]
    return client.get(URL).get_data(as_text=True)


def _sit(data, score=3):
    return models.create_checkpoint_attempt(
        data["student_id"], data["checkpoint_id"], data["task_id"], "quiz", "kern",
        score=score, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid="sess-1")


def test_an_unsat_checkpoint_is_listed_as_open(data, client):
    """The row must exist before it has a result -- an unsat checkpoint IS the open
    work, so it cannot be a join that drops it."""
    body = _get(client, data)
    assert "Checkpoint Kernladung" in body
    assert "Noch nicht bearbeitet" in body


def test_a_normal_aufgabe_is_not_listed(data, client):
    """Only checkpoints. The page is about points, not about progress."""
    assert "Normale Aufgabe" not in _get(client, data)


def test_a_sat_checkpoint_shows_its_points(data, client):
    _sit(data, score=3)
    assert "3 von 3 Punkten" in _get(client, data)


def test_the_teacher_override_is_what_the_student_reads(data, client):
    """effective_checkpoint_score, not the computed one -- a student must never be
    shown a number their teacher has already corrected away."""
    attempt_id = _sit(data, score=0)
    models.set_checkpoint_teacher_review(attempt_id, 2, "Doppelklick", "", 1)
    body = _get(client, data)
    assert "2 von 3 Punkten" in body
    assert "0 von 3 Punkten" not in body


def test_a_rejected_report_asks_for_the_redo(data, client):
    """The case that was invisible: the Aufgabe is ticked off, so nothing sends the
    student back to the question that is now waiting for them."""
    _sit(data, score=2)
    flag_id = models.create_checkpoint_flag(
        data["checkpoint_id"], 0, source="student", student_id=data["student_id"],
        reason_code="ki_falsch")
    models.resolve_checkpoint_flag(flag_id, "abgelehnt", "Antwort war unvollständig.", 1)

    body = _get(client, data)
    assert "noch einmal beantworten" in body


def test_an_open_report_says_the_points_are_not_final(data, client):
    """A report is tied to the sitting it was made in (the session attaches it at
    finish), and that link is what makes the score provisional."""
    attempt_id = _sit(data, score=2)
    models.create_checkpoint_flag(
        data["checkpoint_id"], 0, source="student", student_id=data["student_id"],
        reason_code="ki_falsch", checkpoint_attempt_id=attempt_id)

    body = _get(client, data)
    assert "wird noch geprüft" in body
    assert "2 von 3 Punkten" not in body, "eine vorlaeufige Zahl wird gar nicht gezeigt"


def test_the_page_links_to_the_checkpoint_by_position(data, client):
    """The student-facing URL is a position among VISIBLE subtasks, not the stored
    reihenfolge -- the checkpoint is the second subtask, so position 2."""
    assert "/aufgabe-2/quiz" in _get(client, data)


def test_another_students_result_is_not_shown(data, client, app):
    other = models.create_student("Fremd", "Ada", "quickfox", "bacado42")
    models.add_student_to_klasse(other, data["klasse_id"])
    models.assign_task_to_student(other, data["klasse_id"], data["task_id"])
    models.create_checkpoint_attempt(
        other, data["checkpoint_id"], data["task_id"], "quiz", "kern",
        score=3, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid="sess-other")

    assert "3 von 3 Punkten" not in _get(client, data)
