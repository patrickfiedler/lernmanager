"""Regression test: a rate-limited student's short_answer questions must be
filtered identically on GET and POST, so grading indices stay aligned with
what was actually displayed and answered.

Found while fixing quiz path filtering: the old code only filtered
short_answer questions in the GET branch, after the POST branch's early
return - so POST re-parsed the quiz unfiltered and graded against the
wrong indices whenever a short_answer question wasn't last in the list.
"""
import json
import config
import models

QUIZ = {
    "questions": [
        {"text": "MC zuerst", "options": ["Ja", "Nein"], "correct": [0]},
        {"type": "short_answer", "text": "Erklaere...", "rubric": "..."},
        {"text": "MC danach", "options": ["Ja", "Nein"], "correct": [1]},
    ]
}


def _rate_limited_student_with_topic(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "ratelimittest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                  quiz_json=json.dumps(QUIZ))
    models.assign_task_to_student(student_id, klasse_id, task_id)

    for _ in range(config.LLM_MAX_CALLS_PER_STUDENT_PER_HOUR):
        models.record_llm_usage(student_id, "quiz")

    return student_id, task_id


def test_rate_limited_student_graded_on_correct_remaining_questions(app, client):
    student_id, task_id = _rate_limited_student_with_topic(app)
    assert not models.check_llm_rate_limit(student_id)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    get_resp = client.get("/schueler/thema/testthema/quiz")
    assert get_resp.status_code == 200
    body = get_resp.get_data(as_text=True)
    assert "MC zuerst" in body
    assert "MC danach" in body
    assert "Erklaere" not in body  # short_answer stripped

    # Two MC questions remain -> indices 0 and 1 refer to "MC zuerst"/"MC danach",
    # not the original array positions 0 and 2.
    post_resp = client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0, 1]),
        "answer_map_0": json.dumps([0, 1]),
        "q0": "0",  # "Ja" - correct for "MC zuerst"
        "answer_map_1": json.dumps([0, 1]),
        "q1": "1",  # "Nein" - correct for "MC danach"
    }, follow_redirects=True)
    assert post_resp.status_code == 200

    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        ).fetchone()["id"]
    attempts = models.get_quiz_attempts(student_task_id)
    assert len(attempts) == 1

    antworten = json.loads(attempts[0]["antworten_json"])
    # Correctly filtered, both GET and POST see the same 2-item list ["MC
    # zuerst", "MC danach"] at indices 0/1 - the short_answer question was
    # never shown and has no entry. MC answers are stored as a plain list of
    # submitted option indices - a misaligned index would instead land on the
    # short_answer question and store a dict ({"text": ..., "source": ...}),
    # because config.LLM_ENABLED=False always returns FALLBACK_RESULT
    # (correct=True) regardless of what nonsense text was "graded" - so score
    # alone can't catch this, but the stored answer shape can.
    assert antworten["0"] == [0]
    assert antworten["1"] == [1]
    assert attempts[0]["punkte"] == attempts[0]["max_punkte"] == 2
