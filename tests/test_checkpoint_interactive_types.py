"""ordering/matching inside a Chemie Quiz-checkpoint.

The checkpoint is the surface where these types carry a grade, so the two
things that must hold are: a partly right answer does NOT solve the question
(chemie-data-contract.md § 4a -- the 0/2/3 scale absorbs the retry instead),
and an empty submit never burns a scored attempt.
"""
import json

import models

QUIZ = {
    "questions": [
        {"type": "matching", "text": "Ordne die Begriffe zu.",
         "pairs": [["Anode", "Oxidation"], ["Kathode", "Reduktion"]],
         "distractors": ["Neutralisation"]},
    ]
}
ORDER_QUIZ = {
    "questions": [
        {"type": "ordering", "text": "Reihenfolge?",
         "items": ["Erstens", "Zweitens", "Drittens"]},
    ]
}


def _checkpoint_student(app, quiz=QUIZ):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "cpinteractive", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Elektrochemie", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Begriffe", reihenfolge=0,
        quiz_json=json.dumps(quiz), checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def _answer(client, subtask_id, answer, slug="elektrochemie"):
    return client.post("/schueler/checkpoint/antwort", json={
        "slug": slug, "subtask_id": subtask_id, "question_index": 0, "answer": answer})


def test_page_renders_the_columns_without_the_pairing(app, client):
    student_id, _ = _checkpoint_student(app)
    _login(client, student_id)

    body = client.get("/schueler/thema/elektrochemie/aufgabe-1/quiz").get_data(as_text=True)
    assert "qi-container" in body or "matching" in body
    assert "Neutralisation" in body
    assert '\\"pairs\\"' not in body and '"pairs"' not in body


def test_partly_right_matching_does_not_solve_the_question(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    data = _answer(client, subtask_id, {"Anode": "Oxidation", "Kathode": "Neutralisation"}).get_json()
    assert data["correct"] is False
    assert data["attempts"] == 1
    assert "correct_answer" not in data       # retry-until-correct must stay intact

    data = _answer(client, subtask_id, {"Anode": "Oxidation", "Kathode": "Reduktion"}).get_json()
    assert data["correct"] is True
    assert data["attempts"] == 2


def test_an_empty_matching_submit_never_burns_an_attempt(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    resp = _answer(client, subtask_id, {})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "empty"

    # The rejected submit left no trace: the next real answer is attempt 1, so a
    # first-try solve still scores 3 (chemie-data-contract.md § 3a).
    data = _answer(client, subtask_id, {"Anode": "Oxidation", "Kathode": "Reduktion"}).get_json()
    assert data["attempts"] == 1


def test_an_ordering_question_is_never_empty(app, client):
    # The shuffled order the student was shown is already an answer -- there is
    # nothing to leave blank, so the empty guard must not block a submit.
    student_id, subtask_id = _checkpoint_student(app, ORDER_QUIZ)
    _login(client, student_id)

    resp = _answer(client, subtask_id, ["Drittens", "Zweitens", "Erstens"])
    assert resp.status_code == 200
    assert resp.get_json()["correct"] is False


def test_giving_up_reveals_the_pairing(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    _answer(client, subtask_id, {"Anode": "Reduktion"})

    resp = client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "elektrochemie", "subtask_id": subtask_id, "question_index": 0})
    assert "Anode → Oxidation" in resp.get_json()["correct_answer"]


def test_the_review_log_stores_a_readable_answer(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)
    _answer(client, subtask_id, {"Anode": "Oxidation", "Kathode": "Neutralisation"})

    with models.db_session() as conn:
        row = conn.execute(
            "SELECT answer_text, grader FROM checkpoint_answer ORDER BY id DESC LIMIT 1"
        ).fetchone()
    # JSON, not a Python repr -- the review UI and both exports read this column.
    assert json.loads(row["answer_text"]) == {"Anode": "Oxidation", "Kathode": "Neutralisation"}
    assert row["grader"] == "interactive"
