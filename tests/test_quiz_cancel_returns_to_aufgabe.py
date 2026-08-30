""""Abbrechen" on an Aufgaben-Quiz returns to that Aufgabe, not to the Einführung.

The link carried only the topic slug, so the topic page fell back to the first
*unfinished* subtask -- and an `is_intro` Aufgabe nobody ever ticks stays unfinished
for the whole unit. A student cancelling the quiz for Aufgabe 3 landed on the intro.
"""
import json
import models

QUIZ = {"questions": [{"text": "Frage?", "options": ["a", "b"], "correct": [0]}]}


def _setup(app, client, username):
    app.config["WTF_CSRF_ENABLED"] = False
    sid = models.create_student("Alex", "Schueler", username, "pw123")
    kid = models.create_klasse("K"); models.add_student_to_klasse(sid, kid)
    tid = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                             quiz_json=json.dumps(QUIZ))
    models.create_subtask(tid, "Einfuehrung", reihenfolge=1, is_intro=True)
    models.create_subtask(tid, "Zweite Aufgabe", reihenfolge=2, quiz_json=json.dumps(QUIZ))
    models.assign_task_to_student(sid, kid, tid)
    with client.session_transaction() as s:
        s["student_id"] = sid
    return sid, kid, tid


def test_subtask_quiz_cancel_carries_the_position(app, client):
    _setup(app, client, "quizcancel1")
    page = client.get("/schueler/thema/testthema/aufgabe-2/quiz").get_data(as_text=True)
    assert "/schueler/thema/testthema?aufgabe=2" in page, \
        "cancelling must return to the Aufgabe the quiz belongs to"


def test_topic_quiz_cancel_has_no_position_to_carry(app, client):
    """A topic-level quiz belongs to no single Aufgabe -- the bare slug is correct there."""
    _setup(app, client, "quizcancel2")
    page = client.get("/schueler/thema/testthema/quiz").get_data(as_text=True)
    assert 'href="/schueler/thema/testthema"' in page
