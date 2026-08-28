"""Showing multiple-choice answers as text in the review UI.

MC answers are logged as option indices (`student_checkpoint_answer` stores
`json.dumps([0])`), which made the review page print a bare "[0]" under the
question it answered. These cover resolving that back to the option text, and --
more importantly -- the cases where it must refuse to guess.
"""
import json

import pytest

import app as app_module
import models


MC_QUIZ = {
    "questions": [
        {"type": "multiple_choice",
         "text": "Was verursacht die Farbe der Flamme bei einer Metallsalzprobe?",
         "options": ["Elektronenübergänge in der Atomhülle",
                     "Die Verbrennung des Salzes",
                     "Die Temperatur des Brenners"],
         "correct": [0]},
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
        quiz_json=json.dumps(MC_QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    return {"klasse_id": klasse_id, "student_id": student_id,
            "task_id": task_id, "subtask_id": subtask_id}


def _log(data, answer_text, correct=True, quiz=MC_QUIZ):
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1",
        question_index=0, attempt_no=1, answer_text=answer_text,
        correct=correct, feedback="Richtig!", grader="mc",
    )
    return models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=3, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(quiz), session_uid="sess-1",
    )


def _question(data):
    sessions = app_module._build_checkpoint_sessions(models.get_checkpoint_reviews())
    return sessions[0]["questions"][0]


# ------------------------------------------------------------------- resolution

def test_index_becomes_the_option_text(data):
    _log(data, json.dumps([0]))

    question = _question(data)

    assert question["answers"][0]["answer_display"] == "Elektronenübergänge in der Atomhülle"


def test_correct_option_is_resolved_too(data):
    _log(data, json.dumps([0]))
    assert _question(data)["correct_display"] == "Elektronenübergänge in der Atomhülle"


def test_multi_select_joins_the_chosen_options(data):
    _log(data, json.dumps([0, 2]))

    assert _question(data)["answers"][0]["answer_display"] == (
        "Elektronenübergänge in der Atomhülle · Die Temperatur des Brenners")


def test_image_options_fall_back_to_their_text(data):
    """Options carrying an image are dicts, not strings (CLAUDE.md § Quiz JSON)."""
    quiz = {"questions": [{"type": "multiple_choice", "text": "Welches Spektrum?",
                           "options": [{"text": "Natrium", "image": "/na.png"},
                                       {"image": "/k.png"}],
                           "correct": [0]}]}
    _log(data, json.dumps([0, 1]), quiz=quiz)

    assert _question(data)["answers"][0]["answer_display"] == "Natrium · (Bild)"


# ---------------------------------------------------------- when it must not guess

def test_an_index_outside_the_options_keeps_the_raw_value(data):
    """A later content edit can shorten the options. Showing option 1 for a stored
    2 would put a wrong answer in front of a teacher checking a grade."""
    _log(data, json.dumps([7]))

    question = _question(data)

    assert question["answers"][0]["answer_display"] is None


def test_a_snapshot_without_options_keeps_the_raw_value(data):
    """Sessions predating quiz_snapshot_json have nothing to resolve against."""
    _log(data, json.dumps([0]), quiz={"questions": [{"type": "multiple_choice",
                                                     "text": "Ohne Optionen"}]})

    assert _question(data)["answers"][0]["answer_display"] is None


def test_free_text_answers_are_left_alone(data):
    """fill_blank/short_answer already store the real text -- nothing to map."""
    quiz = {"questions": [{"type": "short_answer", "text": "Erkläre.",
                           "rubric": "Elektronenübergänge."}]}
    _log(data, "Elektronen springen zurück und geben Licht ab", quiz=quiz)

    question = _question(data)

    assert question["answers"][0]["answer_display"] is None
    assert question["correct_display"] is None


# ------------------------------------------------------------------ the surfaces

def test_review_page_shows_text_not_the_index(data, as_admin):
    _log(data, json.dumps([0]))

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "Elektronenübergänge in der Atomhülle" in page
    assert "[0]" not in page


def test_review_page_falls_back_to_the_index_it_cannot_resolve(data, as_admin):
    _log(data, json.dumps([7]))

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "[7]" in page


def test_csv_export_carries_text_and_the_raw_index(data, as_admin):
    _log(data, json.dumps([0]))

    csv = as_admin.get("/admin/checkpoint-pruefung/export.csv").get_data(as_text=True)

    assert "Elektronenübergänge in der Atomhülle" in csv
    assert "antwort_roh" in csv
    assert "[0]" in csv


def test_json_export_carries_text_and_the_raw_index(data, as_admin):
    _log(data, json.dumps([0]))

    payload = as_admin.get("/admin/checkpoint-pruefung/export.json").get_json()

    versuch = payload["sessions"][0]["fragen"][0]["versuche"][0]
    assert versuch["antwort"] == "Elektronenübergänge in der Atomhülle"
    assert versuch["antwort_roh"] == "[0]"
    assert payload["sessions"][0]["fragen"][0]["richtige_antwort"] == \
        "Elektronenübergänge in der Atomhülle"
