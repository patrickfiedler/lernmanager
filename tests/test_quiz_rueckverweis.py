"""`rueckverweis` on a quiz question (MBI request 2026-09-23): after a wrong answer
the result page says where to read it up -- next to the solution, not instead of it.
"""
import json

import pytest

import models
from import_task import _validate_quiz

POINTER = "Lies noch einmal S. 16, Kasten Dateiendungen."
QUIZ = {"questions": [
    {"text": "Welche Endung hat ein Bild?", "options": [".jpg", ".docx"], "correct": [0],
     "rueckverweis": POINTER},
    {"type": "ordering", "text": "Reihenfolge?", "items": ["Eins", "Zwei", "Drei"],
     "rueckverweis": "Schau in Aufgabe 2 nach."},
]}


@pytest.fixture
def result_page(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "rvtest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht", quiz_json=json.dumps(QUIZ))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    def submit(mc, order):
        return client.post("/schueler/thema/testthema/quiz", data={
            "question_order": json.dumps([0, 1]), "q0": mc, "q1": json.dumps(order),
        }, follow_redirects=True).get_data(as_text=True)
    return submit


def test_a_wrong_answer_shows_the_pointer_and_still_the_solution(result_page):
    body = result_page("1", ["Drei", "Zwei", "Eins"])
    assert POINTER in body
    assert "Schau in Aufgabe 2 nach." in body
    assert "Richtig wäre:" in body          # the solution stays visible
    assert body.count("Zum Nachlesen:") == 2


def test_a_right_answer_shows_no_pointer(result_page):
    body = result_page("0", ["Eins", "Zwei", "Drei"])
    assert "Zum Nachlesen:" not in body


def test_only_the_wrong_question_gets_its_pointer(result_page):
    body = result_page("0", ["Drei", "Zwei", "Eins"])
    assert POINTER not in body
    assert "Schau in Aufgabe 2 nach." in body


@pytest.mark.parametrize("value", ["", "   ", ["S. 16"], 16])
def test_import_rejects_a_malformed_pointer(value):
    errors = _validate_quiz({"questions": [
        {"text": "?", "options": ["a", "b"], "correct": [0], "rueckverweis": value}]})
    assert any("'rueckverweis' must be a non-empty string" in e for e in errors)


@pytest.mark.parametrize("key", ["rückverweis", "Rueckverweis", "rueckverweise"])
def test_import_rejects_a_misspelled_key(key):
    errors = _validate_quiz({"questions": [
        {"text": "?", "options": ["a", "b"], "correct": [0], key: "S. 16"}]})
    assert any("did you mean 'rueckverweis'" in e for e in errors)
