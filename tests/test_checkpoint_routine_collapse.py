"""Collapsing questions that went exactly as intended, in the session review page.

A checkpoint session is mostly questions nobody needs to look at, and the page used
to render every one of them at full height -- text, rubric, answer log, calibration
widget, repair form. The two that needed a decision were somewhere in between.

The rule lives in app._mark_question_routine, not in the template, so it is testable
without rendering a page. These tests cover both halves: the Python verdict, and the
one thing the template does with it (`<details open>` or not).

The point of the rule is that it is a conjunction -- ANY irregularity keeps the
question open. So most of this file is one test per way a question can be irregular,
each starting from the same clean session and breaking exactly one thing.
"""
import json
import re

import pytest

import app as app_module
import models


QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern und Hülle."},
        {"type": "short_answer", "text": "Was ist ein Isotop?",
         "rubric": "Gleiche Protonen, andere Neutronen."},
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
        task_id, "### Checkpoint Kernladung", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    return {"klasse_id": klasse_id, "student_id": student_id,
            "task_id": task_id, "subtask_id": subtask_id}


def _clean_session(data, session_uid="sess-1", **answer_kwargs):
    """One session, both questions solved first try -- the routine case."""
    for index in range(2):
        models.create_checkpoint_answer(
            data["student_id"], data["subtask_id"], session_uid,
            question_index=index, attempt_no=1, answer_text=f"Antwort {index}",
            correct=True, feedback="Richtig!", grader="llm",
            llm_model="Qwen/Qwen3-32B-FP8", prompt_version="checkpoint:abc12345",
            judgment_confidence=0.99, **answer_kwargs)
    return models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=3, attempt_count=2, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid=session_uid)


def _routine_flags(attempt_id):
    """[routine?, routine?] for the session's questions, straight from the model."""
    attempts = models.get_checkpoint_reviews(checkpoint_id=None)
    sessions = app_module._build_checkpoint_sessions(
        [a for a in attempts if a["id"] == attempt_id])
    return [q["routine"] for q in sessions[0]["questions"]]


def _answer_ids(attempt_id):
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]
    return [a["id"] for a in answers]


# ------------------------------------------------------------------- the base case

def test_a_clean_question_is_routine(data):
    assert _routine_flags(_clean_session(data)) == [True, True]


def test_a_routine_question_renders_collapsed(data, as_admin):
    _clean_session(data)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert '<details class="checkpoint-question is-routine"' in page
    # Collapsed, not gone: the wording rides in the summary so the row is still
    # recognisable, and the body is one click away.
    assert "Erkläre den Aufbau des Atoms." in page
    assert "Kern und Hülle." in page                 # the rubric, still in the DOM


def test_a_non_routine_question_renders_open(data, as_admin):
    """Every exception below goes through this same rendering path, so it is asserted
    once here rather than in each of them."""
    attempt_id = _clean_session(data)
    models.set_checkpoint_answer_verdict(_answer_ids(attempt_id)[0], 0, "")

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    # Both states on one session: question 1 carries the verdict and stays open,
    # question 2 is untouched and collapses.
    assert re.search(r'<details class="checkpoint-question"\s+open>', page)
    assert re.search(r'<details class="checkpoint-question is-routine"\s+>', page)


# ------------------------------------------------------- one exception at a time

def test_a_second_attempt_is_not_routine(data):
    """Scores 2, not 3 -- the rule reads that one number rather than re-deriving
    'solved, first try, no hint' and risking a second copy of the grading rule."""
    attempt_id = _clean_session(data)
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1", question_index=0,
        attempt_no=2, answer_text="Zweiter Versuch", correct=True,
        feedback="Richtig!", grader="llm", judgment_confidence=0.99)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET checkpoint_attempt_id = ? "
                     "WHERE session_uid = 'sess-1'", (attempt_id,))

    assert _routine_flags(attempt_id) == [False, True]


def test_a_hint_is_not_routine(data):
    attempt_id = _clean_session(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET hints_used_before = 1 "
                     "WHERE question_index = 0 AND checkpoint_attempt_id = ?",
                     (attempt_id,))

    assert _routine_flags(attempt_id) == [False, True]


def test_a_wrong_answer_is_not_routine(data):
    attempt_id = _clean_session(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET correct = 0 "
                     "WHERE question_index = 0 AND checkpoint_attempt_id = ?",
                     (attempt_id,))

    assert _routine_flags(attempt_id) == [False, True]


def test_an_ungraded_answer_is_not_routine(data):
    """correct IS NULL means the LLM never got to it. `scored` can still land on 3 --
    _checkpoint_question_review counts only graded rows -- so this needs its own
    clause, and it is exactly the case a human has to look at."""
    attempt_id = _clean_session(data)
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1", question_index=0,
        attempt_no=2, answer_text="Nicht bewertet", correct=None,
        feedback=None, grader="llm")
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET checkpoint_attempt_id = ? "
                     "WHERE session_uid = 'sess-1'", (attempt_id,))

    assert _routine_flags(attempt_id) == [False, True]


def test_a_give_up_is_not_routine(data):
    """A give-up followed by a correct answer still scores 3, because the give-up row
    is not a counted attempt. It is still the last thing a teacher should have hidden
    from them."""
    attempt_id = _clean_session(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET gave_up = 1 "
                     "WHERE question_index = 0 AND checkpoint_attempt_id = ?",
                     (attempt_id,))

    assert _routine_flags(attempt_id)[0] is False


def test_a_low_confidence_judgment_is_not_routine(data):
    attempt_id = _clean_session(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET judgment_confidence = 0.55 "
                     "WHERE question_index = 0 AND checkpoint_attempt_id = ?",
                     (attempt_id,))

    assert _routine_flags(attempt_id) == [False, True]


def test_an_existing_verdict_is_not_routine(data):
    """_mark_calibration_relevance keeps the widget alive for a recorded verdict so it
    stays clearable. Collapsing the question would hide it again."""
    attempt_id = _clean_session(data)
    models.set_checkpoint_answer_verdict(_answer_ids(attempt_id)[0], 1, "")

    assert _routine_flags(attempt_id) == [False, True]


def test_an_existing_note_alone_is_not_routine(data):
    attempt_id = _clean_session(data)
    models.set_checkpoint_answer_verdict(_answer_ids(attempt_id)[0], None, "nachfragen")

    assert _routine_flags(attempt_id) == [False, True]


def test_a_report_is_not_routine(data):
    """A reported question has no score at all (`scored` is None), so it fails the
    == 3 test -- but it is asserted explicitly because it is the case the whole
    review page exists for."""
    attempt_id = _clean_session(data)
    models.create_checkpoint_flag(
        checkpoint_id=data["subtask_id"], question_index=0, source="student",
        student_id=data["student_id"], checkpoint_attempt_id=attempt_id,
        reason_code="unklar")

    assert _routine_flags(attempt_id) == [False, True]


def test_a_settled_report_is_still_not_routine(data):
    """Settled for the scoring, not for the reading: a rejected report says this
    question has a history, and the row that records it has to stay visible."""
    attempt_id = _clean_session(data)
    flag_id = models.create_checkpoint_flag(
        checkpoint_id=data["subtask_id"], question_index=0, source="student",
        student_id=data["student_id"], checkpoint_attempt_id=attempt_id,
        reason_code="unklar")
    models.resolve_checkpoint_flag(flag_id, "abgelehnt", "", admin_id=1)

    assert _routine_flags(attempt_id) == [False, True]


def test_a_teacher_flag_on_the_question_is_not_routine(data):
    """The class-wide mark carries no attempt, and _build_checkpoint_sessions merges
    it into every session that contains the question -- so it reaches this rule the
    same way a student report does."""
    attempt_id = _clean_session(data)
    models.create_checkpoint_flag(
        checkpoint_id=data["subtask_id"], question_index=1, source="teacher",
        status="kaputt", reason_text="Formulierung mehrdeutig", resolved_by=1)

    assert _routine_flags(attempt_id) == [True, False]


def test_a_hand_set_score_is_not_routine(data, as_admin):
    """A 3 set by hand looks identical to a computed 3 in `scored` -- the override is
    laid over the top. Collapsing it would hide the teacher's own correction from
    them on the next visit."""
    attempt_id = _clean_session(data)
    as_admin.post(
        f"/admin/checkpoint-pruefung/{attempt_id}/frage/0/punkte", data={"punkte": "3"})

    assert _routine_flags(attempt_id) == [False, True]


def test_a_duplicate_is_not_routine(data):
    attempt_id = _clean_session(data)
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1", question_index=0,
        attempt_no=2, answer_text="Antwort 0", correct=True,
        feedback="Richtig!", grader="llm", judgment_confidence=0.99)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET checkpoint_attempt_id = ? "
                     "WHERE session_uid = 'sess-1'", (attempt_id,))

    flags = _routine_flags(attempt_id)
    assert flags == [False, True]


# ------------------------------------------------- duplicates keep working (2.5)

def test_the_duplicate_block_survives_the_collapse(data, as_admin):
    """The <details> the duplicate rows live in is now nested inside the question's
    own <details>. Nesting them is legal and the inner one keeps its own state --
    this asserts the rows are still rendered and still held back."""
    attempt_id = _clean_session(data)
    models.create_checkpoint_answer(
        data["student_id"], data["subtask_id"], "sess-1", question_index=0,
        attempt_no=2, answer_text="Antwort 0", correct=True,
        feedback="Richtig!", grader="llm", judgment_confidence=0.99)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET checkpoint_attempt_id = ? "
                     "WHERE session_uid = 'sess-1'", (attempt_id,))
    kept, _second, duplicate = _answer_ids(attempt_id)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    block = page.index('<details class="checkpoint-duplicates">')
    assert "1 Doppelklick-Verdacht ausgeblendet" in page
    assert page.index(f'data-answer-id="{kept}"') < block
    assert page.index(f'data-answer-id="{duplicate}"') > block


# ------------------------------------------------- the confidence badge (2.3)

def test_a_confident_judgment_gets_no_badge(data, as_admin):
    _clean_session(data)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "unsicher" not in page


def test_a_hesitant_judgment_gets_a_badge_with_its_value(data, as_admin):
    attempt_id = _clean_session(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET judgment_confidence = 0.56 "
                     "WHERE question_index = 0 AND checkpoint_attempt_id = ?",
                     (attempt_id,))

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "🤖 unsicher 0.56" in page


def test_the_badge_threshold_comes_from_the_question_view(data, as_admin):
    """One threshold, one source. A value just under it is badged, one just over it
    is not -- so the two views can never draw the line in different places."""
    import checkpoint_questions

    attempt_id = _clean_session(data)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET judgment_confidence = ? "
                     "WHERE question_index = 0 AND checkpoint_attempt_id = ?",
                     (checkpoint_questions.UNSURE_CONFIDENCE, attempt_id))
        conn.execute("UPDATE checkpoint_answer SET judgment_confidence = ? "
                     "WHERE question_index = 1 AND checkpoint_attempt_id = ?",
                     (checkpoint_questions.UNSURE_CONFIDENCE - 0.01, attempt_id))

    assert _routine_flags(attempt_id) == [True, False]
