"""Teacher-review UI for Chemie Quiz-checkpoints (migrate_048).

Covers the review query, the two kinds of teacher input (score override on the
session, verdict on a single answer), both exports, and the double-click
detection that drives the suggested score correction.
"""
import json

import pytest

import app as app_module
import models


CHECKPOINT_QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern mit Protonen und Neutronen, Hülle mit Elektronen."},
        {"type": "short_answer", "text": "Was ist die Kernladungszahl?",
         "rubric": "Anzahl der Protonen im Kern."},
    ]
}


@pytest.fixture
def checkpoint_data(app):
    """One student in one class with one completed checkpoint session."""
    # The review UI's write paths are POSTs; the suite's convention is to disable
    # CSRF per test module rather than in conftest (see test_checkpoint_quiz.py).
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
    return {
        "klasse_id": klasse_id, "student_id": student_id,
        "task_id": task_id, "subtask_id": subtask_id,
    }


def _log_session(data, answers, score=2, session_uid="sess-1"):
    """Write one checkpoint session: its per-answer log plus the attempt row.

    answers: list of dicts overriding create_checkpoint_answer's arguments.
    """
    for index, answer in enumerate(answers):
        models.create_checkpoint_answer(
            data["student_id"], data["subtask_id"], session_uid,
            question_index=answer.get("question_index", 0),
            attempt_no=answer.get("attempt_no", index + 1),
            answer_text=answer.get("answer_text", "Eine Antwort"),
            correct=answer.get("correct", True),
            feedback=answer.get("feedback", "Passt."),
            grader=answer.get("grader", "llm"),
            llm_model=answer.get("llm_model", "Qwen/Qwen3-32B-FP8"),
            hints_used_before=answer.get("hints_used_before", 0),
            gave_up=answer.get("gave_up", False),
            prompt_version=answer.get("prompt_version", "checkpoint:abc12345"),
        )
    return models.create_checkpoint_attempt(
        data["student_id"], data["subtask_id"], data["task_id"], "quiz", "kern",
        score=score, attempt_count=len(answers), hint_count=0,
        quiz_snapshot_json=json.dumps(CHECKPOINT_QUIZ), session_uid=session_uid,
    )


def _set_timestamps(attempt_id, timestamps):
    """Overwrite the logged timestamps of one session's answers, in order.

    create_checkpoint_answer stamps CURRENT_TIMESTAMP, so every row in a test lands
    in the same second -- fine for most cases, useless for testing the 15s window.
    """
    with models.db_session() as conn:
        rows = conn.execute(
            "SELECT id FROM checkpoint_answer WHERE checkpoint_attempt_id = ? "
            "ORDER BY question_index, attempt_no, id", (attempt_id,)
        ).fetchall()
        for row, timestamp in zip(rows, timestamps):
            conn.execute("UPDATE checkpoint_answer SET timestamp = ? WHERE id = ?",
                         (timestamp, row["id"]))


# ---------------------------------------------------------------- review query

def test_review_lists_session_with_student_and_topic(checkpoint_data):
    _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1},
        {"question_index": 1, "attempt_no": 1},
    ])

    rows = models.get_checkpoint_reviews()
    assert len(rows) == 1
    assert rows[0]["student_name"] == "Kaya Muster"
    assert rows[0]["task_name"] == "1 - Atommodelle"
    assert rows[0]["effective_score"] == 2


def test_review_filters_by_student_class_and_date(checkpoint_data):
    _log_session(checkpoint_data, [{"question_index": 0}])

    assert models.get_checkpoint_reviews(klasse_id=checkpoint_data["klasse_id"])
    assert not models.get_checkpoint_reviews(klasse_id=checkpoint_data["klasse_id"] + 99)
    assert models.get_checkpoint_reviews(student_id=checkpoint_data["student_id"])
    assert not models.get_checkpoint_reviews(student_id=checkpoint_data["student_id"] + 99)
    # A future window must exclude a session logged today.
    assert not models.get_checkpoint_reviews(date_from="2099-01-01")


def test_student_in_two_classes_is_not_listed_twice(checkpoint_data):
    """Class membership is many-to-many -- an EXISTS, not a join (see
    get_checkpoint_reviews), or a second enrolment would duplicate every row."""
    second = models.create_klasse("11d")
    models.add_student_to_klasse(checkpoint_data["student_id"], second)
    _log_session(checkpoint_data, [{"question_index": 0}])

    assert len(models.get_checkpoint_reviews()) == 1


# ------------------------------------------------------- teacher score override

def test_teacher_score_overrides_computed_score(checkpoint_data):
    attempt_id = _log_session(checkpoint_data, [{"question_index": 0}], score=2)

    models.set_checkpoint_teacher_review(attempt_id, 3, "Doppelklick, nicht der Schüler.", 1)

    row = models.get_checkpoint_reviews()[0]
    assert row["score"] == 2                 # the computed score is preserved
    assert row["teacher_score"] == 3
    assert row["effective_score"] == 3       # ... but the override is what counts
    assert row["reviewed_at"] is not None


def test_clearing_the_override_returns_to_the_computed_score(checkpoint_data):
    attempt_id = _log_session(checkpoint_data, [{"question_index": 0}], score=2)
    models.set_checkpoint_teacher_review(attempt_id, 3, "versehentlich", 1)

    models.set_checkpoint_teacher_review(attempt_id, None, "", 1)

    row = models.get_checkpoint_reviews()[0]
    assert row["teacher_score"] is None
    assert row["effective_score"] == 2
    assert row["reviewed_at"] is None


def test_route_rejects_a_score_outside_the_scale(as_admin, checkpoint_data):
    """0/2/3 is a strict three-value category, not a range -- a 1 would silently
    break the Kern-Sperre's `score >= 2` gate."""
    attempt_id = _log_session(checkpoint_data, [{"question_index": 0}], score=2)

    as_admin.post(f"/admin/checkpoint-pruefung/{attempt_id}/bewerten",
                  data={"teacher_score": "1", "teacher_note": ""})

    assert models.get_checkpoint_reviews()[0]["teacher_score"] is None


# ------------------------------------------------------------- answer verdicts

def test_answer_verdict_is_saved_and_leaves_the_score_alone(as_admin, checkpoint_data):
    attempt_id = _log_session(checkpoint_data, [{"question_index": 0, "correct": False}], score=2)
    answer = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id][0]

    response = as_admin.post(
        f"/admin/checkpoint-pruefung/antwort/{answer['id']}/urteil",
        data={"teacher_verdict": "1", "teacher_note": "war eigentlich richtig"},
    )

    assert response.status_code == 200
    saved = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id][0]
    assert saved["teacher_verdict"] == 1
    assert saved["teacher_note"] == "war eigentlich richtig"
    # Calibration only: the grade must not move.
    assert models.get_checkpoint_reviews()[0]["effective_score"] == 2


# -------------------------------------------------------------------- exports

def test_csv_export_marks_llm_disagreement(as_admin, checkpoint_data):
    attempt_id = _log_session(checkpoint_data, [{"question_index": 0, "correct": False}], score=0)
    answer = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id][0]
    models.set_checkpoint_answer_verdict(answer["id"], 1, "KI zu streng")

    response = as_admin.get("/admin/checkpoint-pruefung/export.csv")
    body = response.data.decode("utf-8-sig")

    assert response.status_code == 200
    assert "ki_weicht_ab" in body
    header, row = body.splitlines()[0].split(";"), body.splitlines()[1].split(";")
    assert row[header.index("ki_weicht_ab")] == "1"
    assert row[header.index("prompt_version")] == "checkpoint:abc12345"


def test_json_export_nests_attempts_under_questions(as_admin, checkpoint_data):
    _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": False, "answer_text": "Falsch"},
        {"question_index": 0, "attempt_no": 2, "correct": True, "answer_text": "Richtig"},
    ], score=2)

    export = json.loads(as_admin.get("/admin/checkpoint-pruefung/export.json").data)

    assert len(export["sessions"]) == 1
    question = export["sessions"][0]["fragen"][0]
    assert question["frage"] == "Erkläre den Aufbau des Atoms."
    assert question["bewertungskriterien"].startswith("Kern mit Protonen")
    assert [v["antwort"] for v in question["versuche"]] == ["Falsch", "Richtig"]


# ------------------------------------------------- double-click detection (TODO)

def test_two_identical_answers_seconds_apart_are_flagged(checkpoint_data):
    """The reported classroom bug: one click, no visible response, second click --
    two graded calls, attempts == 2, and a 3 silently becomes a 2."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": True,
         "answer_text": "Kern mit Protonen und Neutronen, Hülle mit Elektronen"},
        {"question_index": 0, "attempt_no": 2, "correct": True,
         "answer_text": "Kern mit Protonen und Neutronen, Hülle mit Elektronen"},
    ], score=2)
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    review = app_module._checkpoint_question_review(answers)

    assert len(review[0]["duplicate_ids"]) == 1
    assert review[0]["scored"] == 2
    assert review[0]["scored_without_duplicates"] == 3


def test_a_genuine_retry_is_not_flagged(checkpoint_data):
    """A real second attempt: different text, after real thinking time, and the
    first one was wrong. Flagging this would hand the teacher a wrong suggestion."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": False,
         "answer_text": "Da sind Elektronen drin", "timestamp": None},
        {"question_index": 0, "attempt_no": 2, "correct": True,
         "answer_text": "Im Kern Protonen und Neutronen, in der Hülle Elektronen"},
    ], score=2)
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    review = app_module._checkpoint_question_review(answers)

    assert review[0]["duplicate_ids"] == set()
    assert review[0]["scored_without_duplicates"] == 2


def test_suggested_score_is_offered_but_not_applied(checkpoint_data):
    """Detection never edits a grade on its own -- it only pre-fills a suggestion
    the teacher has to confirm."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": True, "answer_text": "Gleiche Antwort"},
        {"question_index": 0, "attempt_no": 2, "correct": True, "answer_text": "Gleiche Antwort"},
    ], score=2)

    sessions = app_module._build_checkpoint_sessions(models.get_checkpoint_reviews())

    assert sessions[0]["has_duplicates"] is True
    assert sessions[0]["suggested_score"] == 3
    # Nothing written until the teacher posts the form.
    assert models.get_checkpoint_reviews()[0]["teacher_score"] is None
    assert models.get_checkpoint_reviews()[0]["effective_score"] == 2


def test_identical_answers_outside_the_window_are_not_flagged(checkpoint_data):
    """15 seconds is the line: past it, an identical answer is a student retyping,
    not a click that never got a response."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": True, "answer_text": "Gleiche Antwort"},
        {"question_index": 0, "attempt_no": 2, "correct": True, "answer_text": "Gleiche Antwort"},
    ], score=2)
    _set_timestamps(attempt_id, ["2026-08-26 09:16:03", "2026-08-26 09:17:30"])
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    assert app_module._checkpoint_question_review(answers)[0]["duplicate_ids"] == set()


def test_a_typo_fix_that_flips_the_verdict_is_not_a_duplicate(checkpoint_data):
    """The false positive fuzzy matching would otherwise introduce: two answers one
    character apart, graded differently. That is a real second attempt -- and if it
    were flagged, the score suggestion would be wrong in the student's favour."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": False, "answer_text": "Neutron"},
        {"question_index": 0, "attempt_no": 2, "correct": True, "answer_text": "Neutronen"},
    ], score=2)
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    review = app_module._checkpoint_question_review(answers)
    assert review[0]["duplicate_ids"] == set()
    assert review[0]["scored_without_duplicates"] == 2


def test_a_flagged_duplicate_never_erases_that_the_question_was_solved(checkpoint_data):
    """`solved` is read from all rows, not the filtered ones. Otherwise flagging the
    only correct attempt would suggest 0 points -- the one way a wrong flag could
    actually cost a student marks."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": True, "answer_text": "Richtige Antwort"},
        {"question_index": 0, "attempt_no": 2, "correct": True, "answer_text": "Richtige Antwort"},
    ], score=2)
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    review = app_module._checkpoint_question_review(answers)
    assert len(review[0]["duplicate_ids"]) == 1
    # Not 0: excluding the duplicate removes an attempt, never the solve.
    assert review[0]["scored_without_duplicates"] == 3


def test_near_identical_resend_with_the_same_verdict_is_flagged(checkpoint_data):
    """Fuzzy matching doing its job: same verdict, seconds apart, one stray character.

    (The same-verdict requirement can miss a real double-click if the endpoint judges
    the two identical submissions differently -- temperature 0 is not a determinism
    guarantee on batched fp8 serving. That costs a missed repair, not a wrong one.)
    """
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": True,
         "answer_text": "Im Kern sitzen Protonen und Neutronen"},
        {"question_index": 0, "attempt_no": 2, "correct": True,
         "answer_text": "Im Kern sitzen Protonen und Neutronen."},
    ], score=2)
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    assert len(app_module._checkpoint_question_review(answers)[0]["duplicate_ids"]) == 1


def test_an_ungraded_attempt_is_never_a_duplicate(checkpoint_data):
    """correct=None means the LLM never graded it. Without a verdict there is
    nothing to compare, and guessing would flag a grade change on missing data."""
    attempt_id = _log_session(checkpoint_data, [
        {"question_index": 0, "attempt_no": 1, "correct": None, "answer_text": "Gleiche Antwort",
         "grader": "error"},
        {"question_index": 0, "attempt_no": 2, "correct": True, "answer_text": "Gleiche Antwort"},
    ], score=2)
    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]

    assert app_module._checkpoint_question_review(answers)[0]["duplicate_ids"] == set()
