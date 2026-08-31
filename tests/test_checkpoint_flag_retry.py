"""Redoing the questions whose report a teacher rejected.

A redo is not a second sitting: it renders only the rejected questions and
rescores the existing attempt, so the Aufgabe is not ticked off twice and no
second checkpoint_attempt appears.
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage 2", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}


def _session_with_rejected_report(app, client, as_admin):
    """Question 1 reported and the report rejected; question 2 solved first try."""
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "retrytest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    client.post("/schueler/checkpoint/melden", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": 0, "reason_code": "unklar",
    })
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 1, "answer": [0]
    })
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })

    flag = models.get_checkpoint_flags()[0]
    with client.session_transaction() as sess:
        sess["admin_id"] = models.create_admin("flagadmin", "pw")
        sess.pop("student_id", None)
    client.post(f"/admin/checkpoint-pruefung/meldung/{flag['id']}/urteil",
                data={"status": "abgelehnt", "resolution_note": "Die Frage ist in Ordnung."})
    with client.session_transaction() as sess:
        sess.pop("admin_id", None)
        sess["student_id"] = student_id
    return student_id, subtask_id, flag


def test_the_redo_shows_only_the_rejected_question(app, client, as_admin):
    _session_with_rejected_report(app, client, as_admin)

    body = client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz").get_data(as_text=True)
    assert "Frage 1" in body
    assert "Frage 2" not in body
    assert "Die Frage ist in Ordnung." in body     # the teacher's note comes along


def test_a_solved_redo_rescores_the_same_attempt(app, client, as_admin):
    student_id, subtask_id, flag = _session_with_rejected_report(app, client, as_admin)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    finish = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    }).get_json()

    # Cleanly solved, but a redo cannot score 3 -- the second look is what a retry
    # costs everywhere else in this rule.
    assert finish["score"] == 2
    attempts = models.get_checkpoint_attempts_for_student(student_id)
    assert len(attempts) == 1                       # rescored, not a second sitting
    assert json.loads(attempts[0]["question_scores_json"]) == {"0": 2, "1": 3}
    assert models.get_checkpoint_flags()[0]["status"] == "nachgeholt"
    assert models.checkpoint_score_is_provisional(attempts[0]) is False


def test_an_unsolved_redo_lowers_the_score_to_zero(app, client, as_admin):
    student_id, subtask_id, _ = _session_with_rejected_report(app, client, as_admin)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")

    client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    finish = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    }).get_json()

    assert finish["score"] == 0
    assert models.get_latest_checkpoint_attempt(student_id, subtask_id)["score"] == 0


def test_the_redo_answers_belong_to_the_original_attempt(app, client, as_admin):
    student_id, subtask_id, _ = _session_with_rejected_report(app, client, as_admin)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })

    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    logged = models.get_checkpoint_answers_for_attempt(attempt["id"])
    assert [a["question_index"] for a in logged if a["grader"] != "flagged"] == [0, 1]


def test_once_redone_the_checkpoint_is_a_normal_one_again(app, client, as_admin):
    student_id, subtask_id, _ = _session_with_rejected_report(app, client, as_admin)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })

    body = client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz").get_data(as_text=True)
    assert "Frage 2" in body                        # full checkpoint again
    assert "holst sie jetzt nach" not in body


def test_the_thema_page_points_back_to_the_owed_question(app, client, as_admin):
    """The Aufgabe is already ticked off, so the notice is the only thing that
    would ever send the student back to it."""
    _session_with_rejected_report(app, client, as_admin)

    body = client.get("/schueler/thema/redoxreaktionen").get_data(as_text=True)
    assert "Jetzt nachholen" in body
    assert "/schueler/thema/redoxreaktionen/aufgabe-1/quiz" in body
