"""What a student is shown about a teacher's checkpoint review (migrate_049).

Students see the LLM's score the moment they finish and the teacher reviews later,
so the review has to be visible to them afterwards -- otherwise a corrected mark
never reaches the person it belongs to.

Two rules are load-bearing and asserted end-to-end here:
  1. checkpoint_attempt.teacher_note is the TEACHER's private reason and must never
     render on a student page. Only student_feedback is published.
  2. The page states THAT a session was checked, never when -- no timestamp reaches
     the student.
"""
import json

import pytest

import app as app_module
import models


CHECKPOINT_QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern mit Protonen und Neutronen, Hülle mit Elektronen."},
    ]
}

PRIVATE_NOTE = "Doppelklick, war nicht der Schueler -- intern"
STUDENT_TEXT = "Ich habe den Punkt ergaenzt, deine Begruendung war richtig."


@pytest.fixture
def checkpoint(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    student_id = models.create_student("Muster", "Kaya", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=0,
        quiz_json=json.dumps(CHECKPOINT_QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern",
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    attempt_id = models.create_checkpoint_attempt(
        student_id, subtask_id, task_id, "quiz", "kern",
        score=2, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(CHECKPOINT_QUIZ), session_uid="sess-1",
    )
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    # Derived, not hardcoded: topic_slug() is not plain slugify(name) -- a Seilbahn
    # topic (which "11s" makes this one) gets an 's' injected after the leading
    # number, so a literal slug here silently 404s and every assertion below would
    # be testing an error page.
    task = [t for t in models.get_all_student_tasks(student_id, klasse_id)
            if t["id"] == task_id][0]
    return {"student_id": student_id, "task_id": task_id, "subtask_id": subtask_id,
            "attempt_id": attempt_id, "slug": app_module.topic_slug(task)}


def _page(client, checkpoint):
    """Render the checkpoint page the way a student reaches it.

    No skip-on-404 here: a test that quietly skips when the URL moves would assert
    nothing while still reporting green, and the private-note rule below is exactly
    the kind of thing that must fail loudly.
    """
    resp = client.get(f"/schueler/thema/{checkpoint['slug']}/aufgabe-1/quiz",
                      follow_redirects=True)
    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)
    assert "Thema nicht gefunden" not in html, "topic slug did not resolve"
    return html


def test_unreviewed_session_says_so(checkpoint, client):
    html = _page(client, checkpoint)
    assert "noch nicht geprüft" in html.lower()


def test_confirmed_review_is_shown_as_confirmed(checkpoint, client):
    models.set_checkpoint_teacher_review(checkpoint["attempt_id"], None, "", "", 1)
    html = _page(client, checkpoint)
    assert "geprüft und bestätigt" in html


def test_changed_review_shows_the_new_score_and_the_old_one(checkpoint, client):
    models.set_checkpoint_teacher_review(checkpoint["attempt_id"], 3, PRIVATE_NOTE,
                                         STUDENT_TEXT, 1)
    html = _page(client, checkpoint)
    assert "geprüft und geändert" in html
    assert "3 von 3" in html
    assert STUDENT_TEXT in html


def test_private_teacher_note_never_reaches_the_student(checkpoint, client):
    """The one rule that makes the two-field split worth having."""
    models.set_checkpoint_teacher_review(checkpoint["attempt_id"], 3, PRIVATE_NOTE,
                                         STUDENT_TEXT, 1)
    html = _page(client, checkpoint)
    assert PRIVATE_NOTE not in html
    assert "intern" not in html


def test_no_review_timestamp_reaches_the_student(checkpoint, client):
    """Students are told THAT it was checked, never when."""
    models.set_checkpoint_teacher_review(checkpoint["attempt_id"], 3, "", STUDENT_TEXT, 1)
    row = models.get_checkpoint_reviews()[0]
    reviewed_at = row["reviewed_at"]
    assert reviewed_at  # precondition: it was recorded server-side

    html = _page(client, checkpoint)
    assert reviewed_at not in html
    assert reviewed_at.split(" ")[0] not in html  # not even the date
