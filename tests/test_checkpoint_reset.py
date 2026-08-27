"""Reopening a checkpoint from the review UI.

The point of the feature is that a teacher can hand a checkpoint back for another
try -- after a bug, or after finding a flaw in the unit -- WITHOUT losing what the
student already produced. So these tests check two things in parallel every time:
the progression gate reopens, and the old record is still there.
"""
import json

import pytest

import models


CHECKPOINT_QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern mit Protonen und Neutronen, Hülle mit Elektronen."},
    ]
}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=0,
        quiz_json=json.dumps(CHECKPOINT_QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern",
    )

    students = []
    for nachname, vorname, user in [("Muster", "Kaya", "happypanda"),
                                    ("Beispiel", "Nils", "bravotiger")]:
        student_id = models.create_student(nachname, vorname, user, "bacado42")
        models.add_student_to_klasse(student_id, klasse_id)
        models.assign_task_to_student(student_id, klasse_id, task_id)
        student_task = models.get_student_task(student_id, klasse_id)
        students.append({"id": student_id, "student_task_id": student_task["id"]})

    return {"klasse_id": klasse_id, "task_id": task_id, "subtask_id": subtask_id,
            "students": students}


def _log_session(data, student, score=2, session_uid="sess-1"):
    """One completed checkpoint session for one student, answer log included."""
    models.create_checkpoint_answer(
        student["id"], data["subtask_id"], session_uid,
        question_index=0, attempt_no=1, answer_text="Kern und Hülle",
        correct=True, feedback="Passt.", grader="llm",
        llm_model="Qwen/Qwen3-32B-FP8", prompt_version="checkpoint:abc12345",
    )
    return models.create_checkpoint_attempt(
        student["id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=score, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(CHECKPOINT_QUIZ), session_uid=session_uid,
    )


# ------------------------------------------------------------- the reset itself

def test_reset_reopens_the_quiz_gate(data):
    student = data["students"][0]
    attempt_id = _log_session(data, student)
    assert models.has_passed_subtask_quiz(student["student_task_id"], data["subtask_id"])

    assert models.supersede_checkpoint_attempts([attempt_id]) == 1

    assert not models.has_passed_subtask_quiz(student["student_task_id"],
                                              data["subtask_id"])


def test_reset_keeps_the_record(data):
    """Nothing is deleted: the attempt, its teacher review and its answer log stay."""
    student = data["students"][0]
    attempt_id = _log_session(data, student)
    models.set_checkpoint_teacher_review(attempt_id, 3, "Doppelklick", "Gut gemacht.",
                                         admin_id=1)

    models.supersede_checkpoint_attempts([attempt_id])

    with models.db_session() as conn:
        row = dict(conn.execute("SELECT * FROM checkpoint_attempt WHERE id = ?",
                                (attempt_id,)).fetchone())
    assert row["superseded_at"] is not None
    assert row["score"] == 2
    assert row["teacher_score"] == 3
    assert row["teacher_note"] == "Doppelklick"
    assert row["student_feedback"] == "Gut gemacht."
    assert models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]


def test_reset_is_idempotent(data):
    """A double click must not overwrite the first reset's timestamp."""
    student = data["students"][0]
    attempt_id = _log_session(data, student)

    assert models.supersede_checkpoint_attempts([attempt_id]) == 1
    with models.db_session() as conn:
        first = conn.execute("SELECT superseded_at FROM checkpoint_attempt WHERE id = ?",
                             (attempt_id,)).fetchone()["superseded_at"]

    assert models.supersede_checkpoint_attempts([attempt_id]) == 0
    with models.db_session() as conn:
        second = conn.execute("SELECT superseded_at FROM checkpoint_attempt WHERE id = ?",
                              (attempt_id,)).fetchone()["superseded_at"]
    assert first == second


def test_retake_lands_beside_the_reset_session(data):
    """The new session becomes the live one; the old stays reachable as history."""
    student = data["students"][0]
    old_id = _log_session(data, student, score=0, session_uid="sess-old")
    models.supersede_checkpoint_attempts([old_id])
    new_id = _log_session(data, student, score=3, session_uid="sess-new")

    live = models.get_checkpoint_reviews()
    assert [r["id"] for r in live] == [new_id]

    with_history = models.get_checkpoint_reviews(include_superseded=True)
    assert sorted(r["id"] for r in with_history) == sorted([old_id, new_id])

    assert models.get_latest_checkpoint_attempt(student["id"],
                                                data["subtask_id"])["id"] == new_id


def test_reset_does_not_uncheck_the_aufgabe(data):
    """Only the checkpoint reopens -- the work behind the Aufgabe was still done."""
    student = data["students"][0]
    models.toggle_student_subtask(student["student_task_id"], data["subtask_id"], True)
    attempt_id = _log_session(data, student)

    models.supersede_checkpoint_attempts([attempt_id])

    progress = models.get_student_subtask_progress(student["student_task_id"])
    assert [s for s in progress if s["id"] == data["subtask_id"]][0]["erledigt"]


def test_reset_stops_the_topic_completing_itself(data):
    """Regression: check_task_completion read checkpoint_attempt without filtering
    superseded rows, so a reset Thema counted as finished anyway."""
    student = data["students"][0]
    with models.db_session() as conn:
        conn.execute("UPDATE task SET subtask_quiz_required = 1 WHERE id = ?",
                     (data["task_id"],))
    models.toggle_student_subtask(student["student_task_id"], data["subtask_id"], True)
    attempt_id = _log_session(data, student)
    assert models.check_task_completion(student["student_task_id"])

    models.supersede_checkpoint_attempts([attempt_id])

    assert not models.check_task_completion(student["student_task_id"])


# ------------------------------------------------------------------ the routes

def test_route_resets_one_session(data, client, as_admin):
    student = data["students"][0]
    attempt_id = _log_session(data, student)

    response = client.post(f"/admin/checkpoint-pruefung/{attempt_id}/zuruecksetzen",
                           follow_redirects=True)
    assert response.status_code == 200
    assert not models.has_passed_subtask_quiz(student["student_task_id"],
                                              data["subtask_id"])


def test_bulk_route_resets_the_filtered_selection(data, client, as_admin):
    ids = [_log_session(data, s, session_uid=f"sess-{i}")
           for i, s in enumerate(data["students"])]

    response = client.post("/admin/checkpoint-pruefung/zuruecksetzen",
                           data={"checkpoint_id": data["subtask_id"]},
                           follow_redirects=True)
    assert response.status_code == 200
    assert not models.get_checkpoint_reviews()
    assert len(models.get_checkpoint_reviews(include_superseded=True)) == len(ids)


def test_bulk_route_refuses_an_unfiltered_reset(data, client, as_admin):
    """One click must not be able to reopen every checkpoint in the database."""
    _log_session(data, data["students"][0])

    response = client.post("/admin/checkpoint-pruefung/zuruecksetzen",
                           data={}, follow_redirects=True)
    assert response.status_code == 200
    assert len(models.get_checkpoint_reviews()) == 1


def test_bulk_route_respects_the_class_filter(data, client, as_admin):
    """A student outside the filtered class keeps their session."""
    other_klasse = models.create_klasse("11d")
    outsider_id = models.create_student("Fremd", "Robin", "calmotter", "bacado43")
    models.add_student_to_klasse(outsider_id, other_klasse)
    models.assign_task_to_student(outsider_id, other_klasse, data["task_id"])
    outsider = {"id": outsider_id}
    outsider_attempt = _log_session(data, outsider, session_uid="sess-outsider")
    _log_session(data, data["students"][0], session_uid="sess-inside")

    client.post("/admin/checkpoint-pruefung/zuruecksetzen",
                data={"klasse_id": data["klasse_id"]}, follow_redirects=True)

    assert [r["id"] for r in models.get_checkpoint_reviews()] == [outsider_attempt]


def test_review_page_offers_reset_and_hides_history(data, client, as_admin):
    student = data["students"][0]
    attempt_id = _log_session(data, student)

    page = client.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Checkpoint zurücksetzen" in page

    models.supersede_checkpoint_attempts([attempt_id])
    assert "Kaya Muster" not in client.get(
        "/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Kaya Muster" in client.get(
        "/admin/checkpoint-pruefung?verlauf=1").get_data(as_text=True)
