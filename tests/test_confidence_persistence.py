"""The confidence value has to survive the round trip to be worth recording.

migrate_052 exists so a threshold can be set later on real answers to the questions
actually in use. That only works if the number reaches the row and the export intact --
and if "not measured" stays distinguishable from "measured as zero", which is why the
column is nullable REAL and never defaults to 0.0.
"""
import json

import pytest

import app as app_module
import models


QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre die Elektrolyse.",
         "rubric": "Erzwungene Redoxreaktion."},
    ]
}


@pytest.fixture
def data(app):
    klasse_id = models.create_klasse("12b")
    student_id = models.create_student("Muster", "Kaya", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("12 - Elektrolyse", "", "", "Chemie", "11/12", "")
    subtask_id = models.create_subtask(
        task_id, "### 12.2 Teilgleichungen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    return {"student_id": student_id, "task_id": task_id, "subtask_id": subtask_id}


def _log(data, confidence, session_uid="sess-1"):
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], session_uid,
        question_index=0, attempt_no=1, answer_text="Zink wird reduziert.",
        correct=False, feedback="Unvollständig.", grader="llm",
        llm_model="Qwen3.5-397B-A17B", prompt_version="checkpoint:ad4eadc3",
        judgment_confidence=confidence,
    )
    return models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=0, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid=session_uid,
    )


def test_confidence_is_stored_and_read_back(data):
    attempt_id = _log(data, 0.731)
    answers = models.get_checkpoint_answers_for_attempt(attempt_id)
    assert answers[0]["judgment_confidence"] == pytest.approx(0.731)


def test_unmeasured_stays_null_not_zero(data):
    """A row no LLM graded must not read as "the model was certain it was wrong"."""
    attempt_id = _log(data, None)
    assert models.get_checkpoint_answers_for_attempt(attempt_id)[0]["judgment_confidence"] is None


def test_confidence_reaches_the_export(data):
    _log(data, 0.56)
    sessions = app_module._build_checkpoint_sessions(models.get_checkpoint_reviews())
    rows = app_module._checkpoint_export_rows(sessions)
    assert rows, "export produced no rows"
    assert rows[0]["ki_konfidenz"] == pytest.approx(0.56)
