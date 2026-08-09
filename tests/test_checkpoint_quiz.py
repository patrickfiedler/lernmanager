"""Regression tests for the Chemie Quiz-checkpoint retry-session flow
(_handle_checkpoint_quiz + /schueler/checkpoint/* routes in app.py).
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Was ist die Oxidationszahl von Cl in Cl2?", "options": ["0", "+1", "-1"], "correct": [0]},
    ]
}
QUIZ_MULTI = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage 2", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}
HINTS = ["Denk an die Elektronegativitaet.", "Gleiche Atome teilen sich Elektronen gleich."]


def _checkpoint_student(app, quiz=QUIZ):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "checkpointtest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(quiz), checkpoint_type="quiz", kern_standard_tag="kern",
        checkpoint_hints_json=json.dumps(HINTS),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_checkpoint_page_renders_question_not_answer(app, client):
    student_id, _ = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Oxidationszahl von Cl" in body


def test_wrong_answer_does_not_reveal_correct_and_allows_retry(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    wrong = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })
    data = wrong.get_json()
    assert data["correct"] is False
    assert "correct_answer" not in data
    assert data["attempts"] == 1

    right = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    data = right.get_json()
    assert data["correct"] is True
    assert data["attempts"] == 2


def test_hint_gated_until_after_first_attempt(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    too_early = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert too_early.status_code == 403

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })

    first_hint = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert first_hint.get_json()["hint"] == HINTS[0]

    second_hint = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert second_hint.get_json()["hint"] == HINTS[1]

    no_more = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert no_more.get_json()["hint"] is None


def test_give_up_reveals_correct_answer(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert resp.get_json()["correct_answer"] == "0"


def test_finish_rejects_unresolved_checkpoint(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert resp.status_code == 400


def test_finish_scores_3_on_clean_first_try(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert resp.status_code == 200
    assert resp.get_json()["score"] == 3

    attempts = models.get_checkpoint_attempts_for_student(student_id)
    assert attempts[0]["score"] == 3


def test_finish_scores_worst_case_across_questions(app, client):
    """Per chemie-data-contract.md §3a: consolidation is min(), not average -
    one question solved via hint (2) and one given up (0) -> checkpoint = 0."""
    student_id, subtask_id = _checkpoint_student(app, quiz=QUIZ_MULTI)
    _login(client, student_id)

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })
    client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 1
    })

    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert resp.status_code == 200
    assert resp.get_json()["score"] == 0
