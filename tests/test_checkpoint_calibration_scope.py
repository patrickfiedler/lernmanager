"""Which answers the review UI asks the teacher to calibrate.

The verdict widget ("War die KI-Bewertung richtig?") used to appear under every
answer, including ones no model ever touched -- a multiple-choice index comparison
('mc') or a fill_blank that matched exactly ('match'). That asked the teacher a
question with no answer and fed rows with no KI verdict into the disagreement data
the field exists to collect.
"""
import json

import pytest

import app as app_module
import models


QUIZ = {
    "questions": [
        {"type": "multiple_choice", "text": "Was färbt die Flamme?",
         "options": ["Das Metall-Kation", "Das Anion"], "correct": [0]},
        {"type": "fill_blank", "text": "Natrium färbt die Flamme ___.",
         "answers": ["gelb"]},
        {"type": "short_answer", "text": "Erkläre die Flammenfärbung.",
         "rubric": "Elektronenübergänge."},
    ]
}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    student_id = models.create_student("Muster", "Kaya", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Flammenfärbung", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    return {"student_id": student_id, "task_id": task_id, "subtask_id": subtask_id}


def _log(data, question_index, answer_text, grader, gave_up=False):
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1",
        question_index=question_index, attempt_no=1, answer_text=answer_text,
        correct=True, feedback="Richtig!", grader=grader, gave_up=gave_up,
        llm_model="Qwen/Qwen3-32B-FP8" if grader in ("llm", "fallback") else None,
    )
    return models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=3, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid="sess-1",
    )


def _answer(data, question_index=0):
    sessions = app_module._build_checkpoint_sessions(models.get_checkpoint_reviews())
    for question in sessions[0]["questions"]:
        if question["question_index"] == question_index:
            return question["answers"][0]
    raise AssertionError("question not logged")


# ------------------------------------------------- deterministic: do not ask

def test_multiple_choice_is_not_asked_about(data):
    _log(data, 0, json.dumps([0]), grader="mc")
    assert _answer(data)["show_verdict"] is False


def test_an_exact_fill_blank_match_is_not_asked_about(data):
    """'match' is a string comparison. No model ran, so there is no prompt to tune."""
    _log(data, 1, "gelb", grader="match")
    assert _answer(data, 1)["show_verdict"] is False


def test_an_empty_submit_is_not_asked_about(data):
    _log(data, 1, "", grader="empty")
    assert _answer(data, 1)["show_verdict"] is False


def test_giving_up_is_not_asked_about(data):
    _log(data, 2, "", grader="llm", gave_up=True)
    assert _answer(data, 2)["show_verdict"] is False


# -------------------------------------------------------- model-graded: do ask

def test_an_llm_graded_answer_is_asked_about(data):
    _log(data, 2, "Elektronen springen zurück", grader="llm")
    answer = _answer(data, 2)
    assert answer["show_verdict"] is True
    assert answer["llm_graded"] is True


def test_a_fallback_graded_answer_is_asked_about(data):
    """A fill_blank that missed the exact match went to the LLM after all."""
    _log(data, 1, "goldgelb", grader="fallback")
    assert _answer(data, 1)["show_verdict"] is True


# ------------------------------------------------------ the deterministic escape

def test_an_unresolvable_choice_is_asked_about(data):
    """Patrick's exception: ask when the deterministic path looks broken. Stored
    indices that no longer fit the options mean the question was edited later."""
    _log(data, 0, json.dumps([7]), grader="mc")

    answer = _answer(data)

    assert answer["unresolved_choice"] is True
    assert answer["show_verdict"] is True


def test_a_resolvable_choice_is_not_flagged(data):
    _log(data, 0, json.dumps([0]), grader="mc")
    assert _answer(data)["unresolved_choice"] is False


# --------------------------------------------- nothing already recorded is hidden

def test_an_existing_verdict_keeps_the_widget(data):
    """Verdicts saved before this rule existed must stay visible and clearable."""
    _log(data, 0, json.dumps([0]), grader="mc")
    answer_id = _answer(data)["id"]
    models.set_checkpoint_answer_verdict(answer_id, 1, "")

    assert _answer(data)["show_verdict"] is True


def test_an_existing_note_keeps_the_widget(data):
    _log(data, 0, json.dumps([0]), grader="mc")
    answer_id = _answer(data)["id"]
    models.set_checkpoint_answer_verdict(answer_id, None, "war doch ok")

    assert _answer(data)["show_verdict"] is True


# ------------------------------------------------------------------- the page

def test_page_does_not_ask_about_a_choice_answer(data, as_admin):
    _log(data, 0, json.dumps([0]), grader="mc")

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "War die KI-Bewertung richtig?" not in page
    assert "Stimmt diese automatische Bewertung?" not in page


def test_page_asks_about_an_llm_answer(data, as_admin):
    _log(data, 2, "Elektronen springen zurück", grader="llm")

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "War die KI-Bewertung richtig?" in page


def test_page_flags_and_asks_about_an_unresolvable_choice(data, as_admin):
    _log(data, 0, json.dumps([7]), grader="mc")

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "nicht zuordenbar" in page
    # Not the KI wording -- no model was involved in this one.
    assert "Stimmt diese automatische Bewertung?" in page
    assert "War die KI-Bewertung richtig?" not in page
