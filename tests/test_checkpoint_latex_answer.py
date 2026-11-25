"""B13 (chemie, 2026-11-24): LaTeX pasted from a chatbot must not end in a silent
"could not grade". Two parts: model JSON that quotes the backslash unescaped still
parses, and if grading fails anyway the student is told to drop the formula code.
"""
import json

import pytest

import config
import llm_grading
import models


@pytest.mark.parametrize("raw, feedback", [
    # The model quotes the answer and leaves "\{" unescaped -- not a JSON escape.
    (r'{"correct": true, "feedback": "-1{,}82\{ J} stimmt."}', r"-1{,}82\{ J} stimmt."),
    # Already escaped backslash stays one backslash, valid escapes stay as they are.
    (r'{"correct": true, "feedback": "a\\{ b\n\"c\""}', 'a\\{ b\n"c"'),
])
def test_model_json_with_stray_backslash_parses(raw, feedback):
    assert llm_grading._loads_model_json(raw)["feedback"] == feedback


def test_model_json_that_is_broken_otherwise_still_raises():
    with pytest.raises(json.JSONDecodeError):
        llm_grading._loads_model_json('{"correct": true, "feedback": "abgeschnitten')


def _setup(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "latextest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Volumenarbeit", "", "", "Chemie", "11/12", "pflicht")
    quiz = {"questions": [{"type": "short_answer", "text": "Berechne W.",
                           "rubric": "-1,82 J"}]}
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Volumenarbeit", reihenfolge=0,
        quiz_json=json.dumps(quiz), checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


@pytest.mark.parametrize("answer, mentions_formula", [
    (r"-1{,}82\{ J}", True),
    ("-1,82 J", False),
])
def test_failed_grading_names_formula_code(app, client, monkeypatch, answer, mentions_formula):
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(llm_grading, "grade_answer", lambda *a, **kw: None)
    student_id, subtask_id = _setup(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.post("/schueler/checkpoint/antwort", json={
        "slug": "volumenarbeit", "subtask_id": subtask_id,
        "question_index": 0, "answer": answer})
    assert resp.status_code == 503
    assert ("Formel-Code" in resp.get_json()["message"]) is mentions_formula
