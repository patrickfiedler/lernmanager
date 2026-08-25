"""End-to-end regression test: a topic quiz with a path-restricted question
must stay index-consistent between the GET that renders it, the POST that
grades it, and the result page - for a student who does NOT see that question.

This guards against the class of bug where filtering a quiz's question list
differently across requests desyncs the indices used for grading (see
_filter_quiz_for_path in app.py - it must run identically on every load).
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Sichtbar für alle?", "options": ["Ja", "Nein"], "correct": [0]},
        {"text": "Nur Bergweg?", "path": "bergweg", "options": ["Ja", "Nein"], "correct": [0]},
    ]
}


def _wanderweg_student_with_topic(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "quiztest", "pw123", lernpfad="wanderweg")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                  quiz_json=json.dumps(QUIZ))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id


def test_wanderweg_student_only_graded_on_visible_question(app, client):
    student_id = _wanderweg_student_with_topic(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    get_resp = client.get("/schueler/thema/testthema/quiz")
    assert get_resp.status_code == 200
    body = get_resp.get_data(as_text=True)
    assert "Sichtbar für alle?" in body
    assert "Nur Bergweg?" not in body

    # Only one question was rendered -> question_order has a single entry (index 0)
    post_resp = client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0]),
        "answer_map_0": json.dumps([0, 1]),
        "q0": "0",
    }, follow_redirects=True)
    assert post_resp.status_code == 200

    result_body = post_resp.get_data(as_text=True)
    assert "Sichtbar für alle?" in result_body
    assert "Nur Bergweg?" not in result_body
    # The single visible question was answered correctly -> full score, quiz passed
    assert "bestanden" in result_body.lower() or "100" in result_body
