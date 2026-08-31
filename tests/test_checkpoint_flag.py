"""Students reporting a checkpoint question as broken
(/schueler/checkpoint/melden + the locks it puts on the other routes).

A report is deliberately not a give-up: nothing is graded, the solution stays
hidden, and the question carries no score until a teacher has ruled on it.
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage 2", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}


def _checkpoint_student(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "flagtest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
        checkpoint_hints_json=json.dumps(["Ein Tipp."]),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def _flag(client, subtask_id, question_index, reason="unklar", **extra):
    body = {"slug": "redoxreaktionen", "subtask_id": subtask_id,
            "question_index": question_index, "reason_code": reason}
    body.update(extra)
    return client.post("/schueler/checkpoint/melden", json=body)


def _answer(client, subtask_id, question_index, answer):
    return client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": question_index, "answer": answer
    })


def test_reporting_stores_the_reason_and_the_question_as_it_read(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    assert _flag(client, subtask_id, 0, reason="nicht_behandelt",
                 reason_text="Hatten wir nicht").status_code == 200

    flags = models.get_checkpoint_flags(checkpoint_id=subtask_id)
    assert len(flags) == 1
    assert flags[0]["reason_code"] == "nicht_behandelt"
    assert flags[0]["reason_text"] == "Hatten wir nicht"
    assert flags[0]["question_text_at_flag"] == "Frage 1"
    assert flags[0]["status"] == "offen"
    assert flags[0]["source"] == "student"


def test_a_reported_question_accepts_nothing_more(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    _flag(client, subtask_id, 0)

    assert _answer(client, subtask_id, 0, [0]).status_code == 403
    assert client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    }).status_code == 403

    # Giving up would reveal the solution -- which the student still owes if the
    # teacher rejects the report.
    gave_up = client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert gave_up.status_code == 403
    assert "correct_answer" not in gave_up.get_json()


def test_the_draft_answer_is_kept_as_evidence_but_not_graded(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    _flag(client, subtask_id, 0, reason="unklar", answer=[1])

    with models.db_session() as conn:
        answers = [dict(r) for r in conn.execute(
            "SELECT * FROM checkpoint_answer WHERE student_id = ? AND checkpoint_id = ?",
            (student_id, subtask_id)).fetchall()]
    logged = [a for a in answers if a["grader"] == "flagged"]
    assert len(logged) == 1
    assert logged[0]["correct"] is None
    assert json.loads(logged[0]["answer_text"]) == [1]


def test_ki_bewertung_needs_a_verdict_to_complain_about(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    too_early = _flag(client, subtask_id, 0, reason="ki_bewertung")
    assert too_early.status_code == 400
    assert models.get_checkpoint_flags(checkpoint_id=subtask_id) == []

    _answer(client, subtask_id, 0, [1])          # graded wrong -> now there is a verdict
    assert _flag(client, subtask_id, 0, reason="ki_bewertung").status_code == 200


def test_the_same_question_cannot_be_reported_twice(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    _flag(client, subtask_id, 0)

    with client.session_transaction() as sess:
        sess["checkpoint_progress"] = {}      # a fresh session, e.g. after a re-login

    assert _flag(client, subtask_id, 0).status_code == 400
    assert len(models.get_checkpoint_flags(checkpoint_id=subtask_id)) == 1


def test_an_unknown_reason_is_refused(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    assert _flag(client, subtask_id, 0, reason="weil").status_code == 400
    assert models.get_checkpoint_flags(checkpoint_id=subtask_id) == []


def test_finish_scores_the_remaining_questions_and_records_the_gap(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")

    _flag(client, subtask_id, 0)
    _answer(client, subtask_id, 1, [0])

    finish = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    }).get_json()
    # Optimistic reading (2026-08-31): the reported question is left out of the
    # min(), so the score reflects only what still counts.
    assert finish["score"] == 3
    assert finish["flagged_count"] == 1

    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    assert json.loads(attempt["question_scores_json"]) == {"0": None, "1": 3}
    # ... and the number is marked as not final while the report is open.
    assert models.checkpoint_score_is_provisional(attempt) is True


def test_a_session_where_everything_was_reported_scores_zero(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")

    _flag(client, subtask_id, 0)
    _flag(client, subtask_id, 1)

    finish = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    }).get_json()
    assert finish["score"] == 0
    assert finish["flagged_count"] == 2


def test_the_report_is_tied_to_the_attempt_it_happened_in(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")

    _flag(client, subtask_id, 0)
    _answer(client, subtask_id, 1, [0])
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })

    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    flag = models.get_checkpoint_flags(checkpoint_id=subtask_id)[0]
    assert flag["checkpoint_attempt_id"] == attempt["id"]
