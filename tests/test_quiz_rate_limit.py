"""A used-up LLM pool blocks a quiz with short_answer questions instead of
shortening it (chemie request 2026-08-25, Patrick 2026-09-29).

Before, the short_answer questions were dropped silently and the quiz was
graded against 70 % of the easier questions left -- a student at the limit
passed more easily. A checkpoint still goes on without them (a question not
asked has no score and comes back), but now says so.
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


def _student_with_topic(app, quiz=QUIZ):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "ratelimittest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht", quiz_json=json.dumps(quiz))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, task_id


def _exhaust(student_id, tag="llm_grading", limit=None):
    for _ in range(limit or config.LLM_MAX_CALLS_PER_STUDENT_PER_HOUR):
        models.record_llm_usage(student_id, tag)


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_quiz_with_short_answer_is_blocked_with_a_time(app, client):
    student_id, _ = _student_with_topic(app)
    _exhaust(student_id)
    _login(client, student_id)

    resp = client.get("/schueler/thema/testthema/quiz", follow_redirects=True)
    body = resp.get_data(as_text=True)
    assert "Die KI-Bewertung ist für diese Stunde aufgebraucht" in body
    assert "Das Quiz geht ab" in body and "Uhr wieder" in body
    assert "MC zuerst" not in body


def test_blocked_quiz_saves_no_attempt_on_post(app, client):
    student_id, task_id = _student_with_topic(app)
    _exhaust(student_id)
    _login(client, student_id)

    client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0, 1]),
        "answer_map_0": json.dumps([0, 1]), "q0": "0",
        "answer_map_1": json.dumps([0, 1]), "q1": "1",
    })
    with models.db_session() as conn:
        st_id = conn.execute("SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
                             (student_id, task_id)).fetchone()["id"]
    assert models.get_quiz_attempts(st_id) == []


def test_quiz_without_short_answer_is_not_blocked(app, client):
    mc_only = {"questions": [QUIZ["questions"][0], QUIZ["questions"][2]]}
    student_id, _ = _student_with_topic(app, mc_only)
    _exhaust(student_id)
    _login(client, student_id)

    body = client.get("/schueler/thema/testthema/quiz").get_data(as_text=True)
    assert "MC zuerst" in body and "MC danach" in body


def test_free_at_is_one_hour_after_the_expiring_call(db, monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_CALLS_PER_STUDENT_PER_HOUR", 2)
    sid = models.create_student("A", "B", "freeat", "pw")
    assert models.llm_rate_limit_free_at(sid) is None
    before = models.local_cutoff(minutes=-31)[11:16]
    with models.db_session() as conn:
        for ts in ("2020-01-01 00:00:00", models.local_cutoff(minutes=30), models.local_cutoff(minutes=10)):
            conn.execute("INSERT INTO llm_usage (student_id, question_type, tokens_used, timestamp) "
                         "VALUES (?, 'llm_grading', 0, ?)", (sid, ts))
    # Two calls in the window at the limit of 2: room again when the older
    # (30 min ago) expires, i.e. in about 30 minutes.
    free_at = models.llm_rate_limit_free_at(sid)
    after = models.local_cutoff(minutes=-31)[11:16]
    assert free_at in (before, after)  # a minute boundary may pass in between
