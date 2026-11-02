"""Teacher's read-only look at started, unfinished checkpoints."""
import json

import pytest

import models
from app import app as flask_app

QUIZ = {"questions": [
    {"text": "Frage eins", "options": ["richtig", "falsch"], "correct": [0]},
    {"text": "Frage zwei", "options": ["richtig", "falsch"], "correct": [0]},
]}
URL = "/admin/checkpoint-pruefung?ansicht=angefangen"


def _student(name, klasse_name):
    student_id = models.create_student("Muster", name, name.lower(), "bacado42")
    klasse_id = models.create_klasse(klasse_name)
    models.add_student_to_klasse(student_id, klasse_id)
    return student_id, klasse_id


@pytest.fixture
def data(app):
    student_id, klasse_id = _student("Emma", "11a")
    task_id = models.create_task("Redox", "", "", "Chemie", "11s", "")
    cp = models.create_subtask(task_id, "### Oxidationszahlen", reihenfolge=0,
                               quiz_json=json.dumps(QUIZ), checkpoint_type="quiz")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return {"student_id": student_id, "klasse_id": klasse_id, "task_id": task_id, "cp": cp}


def _answer(data, index=0, correct=1, text="[0]", uid="sess-1"):
    models.create_checkpoint_answer(
        data["student_id"], data["cp"], uid, index, attempt_no=1, answer_text=text,
        correct=correct, feedback=None, grader="mc")


def _admin():
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = 1
    return client


def _sit(data):
    return models.create_checkpoint_attempt(
        data["student_id"], data["cp"], data["task_id"], "quiz", "kern", score=3,
        attempt_count=1, hint_count=0, quiz_snapshot_json=json.dumps(QUIZ),
        session_uid="sess-1")


def test_started_work_is_listed_with_answers_and_the_missing_question(data):
    _answer(data)
    html = _admin().get(URL).get_data(as_text=True)
    assert "Emma" in html
    assert "1 von 2 Fragen erledigt" in html
    assert 'unfinished-answer">richtig<' in html     # the option as words, not "[0]"
    assert "noch nicht beantwortet" in html


def test_finishing_takes_it_off_the_list(data):
    _answer(data)
    _sit(data)
    assert models.get_unfinished_checkpoint_sittings() == []


def test_a_reset_hides_what_came_before_it(data):
    _answer(data, uid="abgebrochen")      # a sitting the attempt below does not stamp
    _sit(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_attempt SET superseded_at = '2999-01-01 00:00:00'")
    assert models.get_unfinished_checkpoint_sittings() == []


def test_a_report_without_an_answer_counts_as_started(data):
    models.create_checkpoint_flag(data["cp"], 1, "student", student_id=data["student_id"],
                                  session_uid="sess-1", reason_code="unklar")
    html = _admin().get(URL).get_data(as_text=True)
    assert "gemeldet" in html and "1 von 2 Fragen erledigt" in html


def test_klasse_filter_and_teacher_scope(data):
    other, other_klasse = _student("Fritz", "11b")
    models.assign_task_to_student(other, other_klasse, data["task_id"])
    _answer(data)
    _answer({**data, "student_id": other}, uid="sess-2")
    names = lambda **kw: {s["vorname"] for s in models.get_unfinished_checkpoint_sittings(**kw)}
    assert names() == {"Emma", "Fritz"}
    assert names(klasse_id=data["klasse_id"]) == {"Emma"}
    assert names(klasse_ids={other_klasse}) == {"Fritz"}
    assert names(klasse_ids=set()) == set()


def test_last_activity_decides_the_date_filter(data):
    _answer(data)
    assert models.get_unfinished_checkpoint_sittings(date_to="2000-01-01") == []
    assert models.get_unfinished_checkpoint_sittings(date_from="2000-01-01")


def test_sandbox_students_stay_out_unless_picked(data):
    _answer(data)
    with models.db_session() as conn:
        conn.execute("UPDATE student SET preview_of_admin = 1 WHERE id = ?", (data["student_id"],))
    assert models.get_unfinished_checkpoint_sittings() == []
    assert models.get_unfinished_checkpoint_sittings(student_id=data["student_id"])


def test_the_tab_changes_nothing_in_the_exports(data):
    _answer(data)
    assert models.get_checkpoint_reviews() == []
