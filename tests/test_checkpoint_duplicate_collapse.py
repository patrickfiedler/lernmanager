"""Collapsing Doppelklick answer rows inside a session card.

A flagged row is >=0.95 identical to the one above it, same verdict, within 15s
(_is_duplicate_submission). Reviewing it means reading the same answer and writing
the same prompt-tuning note twice, so it is held back behind a closed <details>
and the teacher sees only the answers that need reading.

Nothing is hidden from the page: the rows stay in the DOM, one click away.
Assertions use data-answer-id rather than the answer text -- by construction the
two rows say nearly the same thing, so the text cannot tell them apart.
"""
import json

import pytest

import models


# The element, never the bare class name -- the <style> block further down the
# page also contains "checkpoint-duplicates" and would satisfy a loose assertion.
DETAILS = '<details class="checkpoint-duplicates">'

QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern und Hülle."},
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


def _session(data, texts, needs_review=False, session_uid="sess-1"):
    for index, text in enumerate(texts):
        models.create_checkpoint_answer(
            data["student_id"], data["subtask_id"], session_uid,
            question_index=0, attempt_no=index + 1, answer_text=text,
            correct=True, feedback="Richtig!", grader="llm",
            llm_model="Qwen/Qwen3-32B-FP8", prompt_version="checkpoint:abc12345",
        )
    return models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=2, attempt_count=len(texts), hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid=session_uid,
        needs_review=needs_review,
    )


def _answer_ids(attempt_id):
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]
    return [a["id"] for a in answers]


def _double_click(data, **kwargs):
    return _session(data, ["Kern und Hülle", "Kern und Hülle"], **kwargs)


# ------------------------------------------------------------------ the collapse

def test_the_duplicate_row_sits_inside_the_collapsed_block(data, as_admin):
    attempt_id = _double_click(data)
    kept, duplicate = _answer_ids(attempt_id)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    block = page.index(DETAILS)
    assert page.index(f'data-answer-id="{kept}"') < block
    assert page.index(f'data-answer-id="{duplicate}"') > block


def test_the_summary_counts_what_it_hid(data, as_admin):
    _double_click(data)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "1 Doppelklick-Verdacht ausgeblendet" in page


def test_the_block_is_closed_by_default(data, as_admin):
    _double_click(data)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert DETAILS in page
    assert '<details class="checkpoint-duplicates" open>' not in page


def test_the_hidden_row_is_still_fully_rendered(data, as_admin):
    """One click away, not gone -- including its verdict widget, which the page JS
    binds by data-answer-id (elements inside a closed details are still in the DOM)."""
    attempt_id = _double_click(data)
    duplicate = _answer_ids(attempt_id)[1]

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert f'data-answer-id="{duplicate}"' in page
    assert "is-duplicate" in page
    assert "Doppelklick-Verdacht</span>" in page      # the per-row badge survives


def test_a_session_without_duplicates_renders_no_block(data, as_admin):
    _session(data, ["Kern und Hülle"])

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert DETAILS not in page


def test_a_triple_click_hides_both_resends(data, as_admin):
    """_checkpoint_question_review compares against the last unflagged row, so rows
    2 and 3 are both flagged and only the original stays visible."""
    attempt_id = _session(data, ["Kern und Hülle"] * 3)
    kept, second, third = _answer_ids(attempt_id)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    block = page.index(DETAILS)
    assert "2 Doppelklick-Verdacht ausgeblendet" in page
    assert page.index(f'data-answer-id="{kept}"') < block
    assert page.index(f'data-answer-id="{second}"') > block
    assert page.index(f'data-answer-id="{third}"') > block


# ------------------------------------------------------------------ the auto-open

def test_a_doppelklick_no_longer_opens_its_session(data, as_admin):
    """The old rule inverted the page: routine duplicates expanded themselves while
    the sessions that needed a human stayed collapsed."""
    _double_click(data)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "checkpoint-session\" open" not in page
    assert DETAILS in page                      # the session is still listed


def test_a_needs_review_session_still_opens(data, as_admin):
    """LLM grading was unavailable and a question was scored as a give-up. That is
    the one flag that genuinely wants a teacher's eyes."""
    _session(data, ["Kern und Hülle"], needs_review=True)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "checkpoint-session\" open" in page
