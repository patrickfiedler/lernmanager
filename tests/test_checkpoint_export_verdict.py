"""What the export says about a teacher's calibration click.

`teacher_verdict` answers the admin UI's question "War die KI-Bewertung richtig?"
(ja/nein). It does NOT record what the answer was. The export used to flag
disagreement as `teacher_verdict != correct`, which reports the opposite on the two
most common rows: a confirmed "falsch" (0/0) looked like agreement, and an overruled
"falsch" (0/1) looked like disagreement. In the 2026-08-26 production export that was
72 of 103 judged rows -- and reading the field as the answer's correctness inverted
the ground truth of a whole prompt evaluation before it was caught.
"""
import json

import pytest

import app as app_module
import models


QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Nenne eine Gemeinsamkeit.",
         "rubric": "Beide sind Redoxreaktionen."},
    ]
}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("12a")
    student_id = models.create_student("Muster", "Kaya", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("12 - Elektrolyse", "", "", "Chemie", "12s", "")
    subtask_id = models.create_subtask(
        task_id, "### 12.3 Galvanisch vs. Elektrolyse", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    return {"student_id": student_id, "task_id": task_id, "subtask_id": subtask_id}


def _row(data, ki_correct, teacher_verdict):
    """Log one LLM-graded answer, record a calibration click, return its export row."""
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1",
        question_index=0, attempt_no=1, answer_text="beide haben eine Redoxreaktion",
        correct=ki_correct, feedback="…", grader="llm", gave_up=False,
        llm_model="Qwen3.5-397B-A17B",
    )
    models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=3, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid="sess-1",
    )
    sessions = app_module._build_checkpoint_sessions(models.get_checkpoint_reviews())
    answer_id = sessions[0]["questions"][0]["answers"][0]["id"]
    models.set_checkpoint_answer_verdict(answer_id, teacher_verdict, None)

    rows = app_module._checkpoint_export_rows(
        app_module._build_checkpoint_sessions(models.get_checkpoint_reviews()))
    return rows[0]


# ------------------------------------------------------------- disagreement flag

def test_an_overruled_wrong_verdict_is_a_disagreement(data):
    """The case that dominated production: KI said falsch, teacher said "nein,
    das war nicht richtig bewertet". The old formula scored this as agreement."""
    row = _row(data, ki_correct=False, teacher_verdict=0)
    assert row["ki_weicht_ab"] == 1


def test_a_confirmed_wrong_verdict_is_not_a_disagreement(data):
    """KI said falsch, teacher clicked ja. The old formula flagged this."""
    row = _row(data, ki_correct=False, teacher_verdict=1)
    assert row["ki_weicht_ab"] == 0


def test_a_confirmed_correct_verdict_is_not_a_disagreement(data):
    row = _row(data, ki_correct=True, teacher_verdict=1)
    assert row["ki_weicht_ab"] == 0


def test_an_overruled_correct_verdict_is_a_disagreement(data):
    row = _row(data, ki_correct=True, teacher_verdict=0)
    assert row["ki_weicht_ab"] == 1


# ----------------------------------------------- the answer's actual correctness

def test_an_overruled_wrong_verdict_means_the_answer_was_right(data):
    row = _row(data, ki_correct=False, teacher_verdict=0)
    assert row["antwort_war_richtig"] == 1


def test_a_confirmed_wrong_verdict_means_the_answer_was_wrong(data):
    row = _row(data, ki_correct=False, teacher_verdict=1)
    assert row["antwort_war_richtig"] == 0


def test_an_overruled_correct_verdict_means_the_answer_was_wrong(data):
    row = _row(data, ki_correct=True, teacher_verdict=0)
    assert row["antwort_war_richtig"] == 0


def test_an_unjudged_answer_has_no_derived_correctness(data):
    """NULL, not 0 -- an unjudged answer must not read as a wrong one."""
    row = _row(data, ki_correct=True, teacher_verdict=None)
    assert row["antwort_war_richtig"] is None
    assert row["ki_weicht_ab"] == 0
