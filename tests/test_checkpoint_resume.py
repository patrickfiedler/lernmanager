"""Picking up a checkpoint that ran out of lesson.

The counters that decide a checkpoint's score live in the Flask session cookie,
so before this a student whose lesson ended -- or whose school PC wiped its
browser data at logout -- came back to a blank checkpoint and had to redo
questions they had already solved. Chemie's requirement of 2026-09-01: the
hardness of the Kern gate is completeness, not time.
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Frage eins", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage zwei", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage drei", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}
SLUG = "redoxreaktionen"
URL = f"/schueler/thema/{SLUG}/aufgabe-1/quiz"


def _checkpoint(client, quiz=None):
    student_id = models.create_student("Test", "Schueler", "resumetest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(quiz or QUIZ), checkpoint_type="quiz",
        kern_standard_tag="kern",
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    return student_id, subtask_id


def _answer(client, subtask_id, index, answer=None):
    return client.post("/schueler/checkpoint/antwort", json={
        "slug": SLUG, "subtask_id": subtask_id, "question_index": index,
        "answer": [0] if answer is None else answer,
    })


def _lesson_ends(client, student_id):
    """What the bell does: the browser session goes, the login stays."""
    with client.session_transaction() as sess:
        sess.pop("checkpoint_progress", None)
        sess["student_id"] = student_id


def test_solved_questions_are_not_asked_again(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, subtask_id = _checkpoint(client)
    client.get(URL)
    _answer(client, subtask_id, 0)
    _lesson_ends(client, student_id)

    body = client.get(URL).get_data(as_text=True)
    assert "Frage eins" not in body
    assert "Frage zwei" in body and "Frage drei" in body
    assert "1 von 3 Fragen" in body      # the banner says where the missing one went


def test_the_resumed_sitting_scores_as_one_attempt(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, subtask_id = _checkpoint(client)
    client.get(URL)
    _answer(client, subtask_id, 0)
    _lesson_ends(client, student_id)

    client.get(URL)
    _answer(client, subtask_id, 1)
    _answer(client, subtask_id, 2)
    finish = client.post("/schueler/checkpoint/fertig",
                         json={"slug": SLUG, "subtask_id": subtask_id}).get_json()

    # 3, not 2: every question was solved first try. The interruption is not a retry.
    assert finish["score"] == 3
    attempts = models.get_checkpoint_attempts_for_student(student_id)
    assert len(attempts) == 1


def test_a_wrong_answer_before_the_break_still_costs_its_point(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, subtask_id = _checkpoint(client)
    client.get(URL)
    _answer(client, subtask_id, 0, answer=[1])      # wrong
    _lesson_ends(client, student_id)

    client.get(URL)
    for index in (0, 1, 2):
        _answer(client, subtask_id, index)
    finish = client.post("/schueler/checkpoint/fertig",
                         json={"slug": SLUG, "subtask_id": subtask_id}).get_json()

    # The failed attempt survived the break -- resuming must not launder it into a
    # clean first try.
    assert finish["score"] == 2


def test_a_reported_question_stays_reported_across_the_break(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, subtask_id = _checkpoint(client)
    client.get(URL)
    client.post("/schueler/checkpoint/melden", json={
        "slug": SLUG, "subtask_id": subtask_id, "question_index": 0,
        "reason_code": "unklar",
    })
    _lesson_ends(client, student_id)

    body = client.get(URL).get_data(as_text=True)
    assert "Frage eins" not in body     # reported questions are finished, not open

    _answer(client, subtask_id, 1)
    _answer(client, subtask_id, 2)
    finish = client.post("/schueler/checkpoint/fertig",
                         json={"slug": SLUG, "subtask_id": subtask_id}).get_json()
    assert finish["flagged_count"] == 1
    assert finish["score"] == 3         # the reported one carries no score, per §3a


def test_two_interruptions_merge_into_one_sitting(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, subtask_id = _checkpoint(client)
    client.get(URL)
    _answer(client, subtask_id, 0)
    _lesson_ends(client, student_id)
    client.get(URL)
    _answer(client, subtask_id, 1)
    _lesson_ends(client, student_id)

    body = client.get(URL).get_data(as_text=True)
    assert "2 von 3 Fragen" in body     # the first half is not lost to the second break

    _answer(client, subtask_id, 2)
    finish = client.post("/schueler/checkpoint/fertig",
                         json={"slug": SLUG, "subtask_id": subtask_id}).get_json()
    assert finish["score"] == 3
    assert len(models.get_checkpoint_attempts_for_student(student_id)) == 1


def test_a_teachers_reset_is_not_undone_by_resuming(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, subtask_id = _checkpoint(client)
    client.get(URL)
    for index in (0, 1, 2):
        _answer(client, subtask_id, index)
    client.post("/schueler/checkpoint/fertig", json={"slug": SLUG, "subtask_id": subtask_id})

    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    models.supersede_checkpoint_attempts([attempt["id"]])
    _lesson_ends(client, student_id)

    # A reset means start over: all three questions come back, no resume banner.
    body = client.get(URL).get_data(as_text=True)
    for text in ("Frage eins", "Frage zwei", "Frage drei"):
        assert text in body
    assert "Du machst hier weiter" not in body


def test_nothing_to_resume_leaves_a_fresh_checkpoint_alone(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    _checkpoint(client)
    body = client.get(URL).get_data(as_text=True)
    assert "Du machst hier weiter" not in body
    assert "Frage eins" in body
