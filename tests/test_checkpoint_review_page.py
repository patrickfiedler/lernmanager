"""The read-only review of a finished checkpoint (Patrick, 2026-09-16).

Three findings behind it: the page showed the session min() as "X von 3 Punkten"
while chemie's grade averages over questions; "Ansehen" started a full new sitting,
and finishing it wrote a second attempt (retake until 3); and nothing showed what
happened per question. Decided: no retake without a teacher reset, points per
question, no model answer and no criteria.
"""
import json

import pytest

import app as app_module
import models

RUBRIC = "GEHEIM-RUBRIK Kern mit Protonen und Neutronen"
QUIZ = {"questions": [
    {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.", "rubric": RUBRIC},
    {"type": "multiple_choice", "text": "Welches Teilchen ist negativ?",
     "options": ["Proton", "Elektron"], "correct": [1]},
    {"type": "short_answer", "text": "Was ist ein Isotop?", "rubric": RUBRIC},
]}
PRIVATE_NOTE = "INTERNE-NOTIZ nicht fuer Schueler"


@pytest.fixture
def cp(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    student_id = models.create_student("Muster", "Kaya", "reviewkid", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=0, quiz_json=json.dumps(QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    task = models.get_all_student_tasks(student_id, klasse_id)[0]
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    return {"student_id": student_id, "subtask_id": subtask_id, "task_id": task_id,
            "slug": app_module.topic_slug(task)}


def _finish(cp, scores, session_uid="sess-1"):
    """One finished sitting: Q1 wrong then right with an AI hint, Q2 right first
    time, Q3 given up (the give-up row stores the revealed solution as feedback)."""
    sid, cid = cp["student_id"], cp["subtask_id"]
    wrong = models.create_checkpoint_answer(sid, cid, session_uid, 0, 1, "Nur Elektronen.",
                                            False, "LLM-FEEDBACK nennt Protonen", "llm")
    models.set_checkpoint_answer_hint(wrong["id"], "ok", text="Was gehört noch in den Kern?")
    models.create_checkpoint_answer(sid, cid, session_uid, 0, 2, "Kern und Hülle.",
                                    True, "ok", "llm")
    models.create_checkpoint_answer(sid, cid, session_uid, 1, 1, "[1]", True, None, "mc")
    models.create_checkpoint_answer(sid, cid, session_uid, 2, 1, None, False, RUBRIC,
                                    "gaveup", gave_up=True)
    return models.create_checkpoint_attempt(
        sid, cid, cp["task_id"], "quiz", "kern", score=min(v for v in scores.values() if v is not None),
        attempt_count=4, hint_count=0, quiz_snapshot_json=json.dumps(QUIZ),
        session_uid=session_uid, question_scores_json=json.dumps(scores))


def _page(client, cp):
    return client.get(f"/schueler/thema/{cp['slug']}/aufgabe-1/quiz").get_data(as_text=True)


def test_a_finished_checkpoint_opens_as_review_not_as_a_new_sitting(cp, client):
    _finish(cp, {"0": 2, "1": 3, "2": 0})
    html = _page(cp=cp, client=client)
    assert "Abgeschlossen" in html
    assert 'id="check-btn"' not in html
    assert "Punkte je Frage" in html


def test_points_are_shown_per_question_not_as_the_minimum(cp, client):
    _finish(cp, {"0": 2, "1": 3, "2": 0})
    text = " ".join(_page(client, cp).split())
    assert "F1&nbsp;<strong>2</strong>" in text and "F2&nbsp;<strong>3</strong>" in text
    assert "von 3 Punkten" not in text


def test_each_question_says_why(cp, client):
    _finish(cp, {"0": 2, "1": 3, "2": 0})
    text = " ".join(_page(client, cp).split())
    assert "im 2. Versuch richtig" in text
    assert "im ersten Versuch richtig" in text
    assert "aufgegeben" in text


def test_answers_and_ai_hints_are_shown_but_never_solution_criteria_or_notes(cp, client):
    attempt_id = _finish(cp, {"0": 2, "1": 3, "2": 0})
    models.set_checkpoint_teacher_review(attempt_id, None, PRIVATE_NOTE, "Gut gemacht.", 1)
    html = _page(client, cp)
    assert "Kern und Hülle." in html
    assert "Was gehört noch in den Kern?" in html
    assert ">Elektron</div>" in html              # multiple choice shown as words, not "[1]"
    assert "Gut gemacht." in html
    assert "GEHEIM-RUBRIK" not in html            # neither criteria nor give-up solution
    assert "LLM-FEEDBACK" not in html             # grader sentence was never shown live
    assert PRIVATE_NOTE not in html


def test_kern_is_stated_in_words(cp, client):
    _finish(cp, {"0": 2, "1": 3, "2": 0})
    assert "noch nicht jede Frage ist gelöst" in _page(client, cp)


@pytest.mark.parametrize("route", ["antwort", "aufgeben", "melden", "hinweis", "fertig"])
def test_a_finished_checkpoint_refuses_every_write(cp, client, route):
    """A tab left open from before finishing must not grade, reveal or write a second
    attempt -- that was the retake-until-3 path."""
    _finish(cp, {"0": 2, "1": 3, "2": 0})
    response = client.post(f"/schueler/checkpoint/{route}", json={
        "slug": cp["slug"], "subtask_id": cp["subtask_id"], "question_index": 0,
        "answer": "noch mal", "reason_code": "unklar"})
    assert response.status_code == 409
    assert "schon abgeschlossen" in response.get_json()["message"]


def test_an_owed_question_opens_the_redo_and_names_the_question(cp, client):
    """Chemie request 2026-09-13: a question the teacher sent back."""
    attempt_id = _finish(cp, {"0": 2, "1": 3, "2": 0})
    models.create_checkpoint_flag(cp["subtask_id"], 2, source="teacher",
                                  student_id=cp["student_id"], status="nachbesserung",
                                  checkpoint_attempt_id=attempt_id, resolved_by=1)
    text = " ".join(_page(client, cp).split())
    assert 'id="check-btn"' in text
    assert "Du holst hier Frage 3 nach" in text
    assert "ohne Punktabzug" in text


def test_the_thema_page_names_the_owed_question(cp, client):
    attempt_id = _finish(cp, {"0": 2, "1": 3, "2": 0})
    models.create_checkpoint_flag(cp["subtask_id"], 2, source="teacher",
                                  student_id=cp["student_id"], status="nachbesserung",
                                  checkpoint_attempt_id=attempt_id, resolved_by=1)
    text = " ".join(client.get(f"/schueler/thema/{cp['slug']}").get_data(as_text=True).split())
    assert "wartet Frage 3 noch auf dich" in text


def test_a_teacher_reset_opens_the_checkpoint_again(cp, client):
    attempt_id = _finish(cp, {"0": 2, "1": 3, "2": 0})
    models.supersede_checkpoint_attempts([attempt_id])
    html = _page(client, cp)
    assert 'id="check-btn"' in html
    assert "noch einmal geöffnet" in html


def test_marking_the_sitting_reviewed_keeps_the_owed_question(cp, client):
    """Chemie request 2026-09-13, last point: the teacher ticks the session off as
    reviewed, and the returned question must still be owed."""
    attempt_id = _finish(cp, {"0": 2, "1": 3, "2": 0})
    models.create_checkpoint_flag(cp["subtask_id"], 2, source="teacher",
                                  student_id=cp["student_id"], status="nachbesserung",
                                  checkpoint_attempt_id=attempt_id, resolved_by=1)
    models.set_checkpoint_teacher_review(attempt_id, None, "", "", 1)
    assert cp["subtask_id"] in models.get_checkpoints_awaiting_retry(cp["student_id"])
    assert "Du holst hier Frage 3 nach" in " ".join(_page(client, cp).split())
