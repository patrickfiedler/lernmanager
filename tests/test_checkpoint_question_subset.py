"""A checkpoint whose rendered question list is a SUBSET of the stored quiz.

That happens whenever the student's hourly LLM budget for checkpoints is spent:
_handle_checkpoint_quiz drops the short_answer questions, and everything that walks
the stored quiz by position is then off by one -- the client used to send its own
array position as `question_index`, and finish waited for answers to questions the
student was never shown.
"""
import json
import config
import models

QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erklaere die Oxidation.", "rubric": "Elektronenabgabe"},
        {"text": "Oxidationszahl von Cl in Cl2?", "options": ["0", "+1", "-1"], "correct": [0]},
    ]
}


def _checkpoint_student(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "subsettest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


def _exhaust_checkpoint_budget(student_id):
    for _ in range(config.LLM_MAX_CHECKPOINT_CALLS_PER_STUDENT_PER_HOUR):
        models.record_llm_usage(student_id, "checkpoint_quiz")


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_rendered_questions_carry_their_index_in_the_stored_quiz(app, client):
    student_id, _ = _checkpoint_student(app)
    _exhaust_checkpoint_budget(student_id)
    _login(client, student_id)

    body = client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz").get_data(as_text=True)

    assert "Erklaere die Oxidation" not in body   # dropped: no LLM budget left
    assert '"index": 1' in body                   # ... but the MC question keeps index 1


def test_finish_scores_only_the_questions_that_were_rendered(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _exhaust_checkpoint_budget(student_id)
    _login(client, student_id)

    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    answer = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 1, "answer": [0]
    })
    assert answer.get_json()["correct"] is True

    finish = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert finish.status_code == 200
    assert finish.get_json()["score"] == 3
