"""Regression tests for the topic re-entry resume-point bug (todo.md § Bugs):
param-less entry (dashboard "Weiter lernen", quiz Zurück/Abbrechen) used to
always land on subtask position 1 instead of actual progress.
"""
import models
from app import _resolve_resume_subtask


def test_resume_at_first_incomplete_when_nothing_done():
    subtasks = [
        {"id": 1, "erledigt": False, "quiz_json": None},
        {"id": 2, "erledigt": False, "quiz_json": None},
    ]
    assert _resolve_resume_subtask(subtasks, {})["id"] == 1


def test_resume_skips_completed_subtasks():
    subtasks = [
        {"id": 1, "erledigt": True, "quiz_json": None},
        {"id": 2, "erledigt": False, "quiz_json": None},
    ]
    assert _resolve_resume_subtask(subtasks, {})["id"] == 2


def test_resume_stays_on_subtask_with_unpassed_quiz():
    subtasks = [
        {"id": 1, "erledigt": True, "quiz_json": '{"questions": []}'},
        {"id": 2, "erledigt": False, "quiz_json": None},
    ]
    assert _resolve_resume_subtask(subtasks, {1: False})["id"] == 1


def test_resume_advances_past_subtask_with_passed_quiz():
    subtasks = [
        {"id": 1, "erledigt": True, "quiz_json": '{"questions": []}'},
        {"id": 2, "erledigt": False, "quiz_json": None},
    ]
    assert _resolve_resume_subtask(subtasks, {1: True})["id"] == 2


def test_resume_falls_back_to_last_when_everything_done():
    subtasks = [
        {"id": 1, "erledigt": True, "quiz_json": None},
        {"id": 2, "erledigt": True, "quiz_json": None},
    ]
    assert _resolve_resume_subtask(subtasks, {})["id"] == 2


def test_resume_empty_list():
    assert _resolve_resume_subtask([], {}) is None


def test_param_less_reentry_shows_actual_progress_not_position_one(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "resumetest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Resumethema", "", "", "MBI", "5", "")
    s1 = models.create_subtask(task_id, "Erste Aufgabe", reihenfolge=0)
    models.create_subtask(task_id, "Zweite Aufgabe", reihenfolge=1)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)
        ).fetchone()["id"]
    models.toggle_student_subtask(student_task_id, s1, True)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.get("/schueler/thema/resumethema")
    body = resp.get_data(as_text=True)
    # "Erste Aufgabe" still appears in the collapsed "already completed" list --
    # the real signal is that the active content area shows the second task.
    assert '<div class="task-content markdown-content">' in body
    content_start = body.index('<div class="task-content markdown-content">')
    active_content = body[content_start:content_start + 300]
    assert "Zweite Aufgabe" in active_content
    assert "Erste Aufgabe" not in active_content
