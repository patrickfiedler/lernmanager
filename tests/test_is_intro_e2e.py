"""End-to-end regression tests for is_intro-driven Aufgabe labeling.

aufgabe_label_filter used to infer 'E' purely from position==1 (app.py).
Switched to reading subtask.is_intro directly so a unit can put the intro
subtask anywhere without breaking the label - see todo.md 'Implement
is_intro'. These tests deliberately put the intro subtask at position 2
to prove the label follows the flag, not the position.
"""
import re

import models


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def _setup_task_with_intro_at_position_2(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "introtest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "")

    models.create_subtask(task_id, "Vorbereitung", reihenfolge=0)
    models.create_subtask(task_id, "Einführung", reihenfolge=1, is_intro=1)
    models.create_subtask(task_id, "Aufgabe A", reihenfolge=2)
    models.create_subtask(task_id, "Aufgabe B", reihenfolge=3)

    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id


def test_e_label_follows_is_intro_not_position_1(app, client):
    student_id = _setup_task_with_intro_at_position_2(app)
    _login(client, student_id)

    resp = client.get("/schueler/thema/testthema")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200

    def is_intro_of(position):
        m = re.search(rf'data-subtask-position="{position}".*?data-is-intro="(true|false)"', body, re.DOTALL)
        return m.group(1) == 'true'

    def title_of(position):
        m = re.search(rf'data-subtask-position="{position}".*?title="Aufgabe ([^"]+)"', body, re.DOTALL)
        return m.group(1)

    # Position 1 (Vorbereitung) is NOT flagged is_intro -> gets a number, not 'E'
    assert is_intro_of(1) is False
    assert title_of(1) == '1'
    # Position 2 (Einführung) IS flagged is_intro -> gets 'E'
    assert is_intro_of(2) is True
    assert title_of(2) == 'E'
    # Position 3 (Aufgabe A) is the 2nd non-intro subtask
    assert title_of(3) == '2'


def test_progress_denominator_excludes_is_intro(app, client):
    student_id = _setup_task_with_intro_at_position_2(app)
    _login(client, student_id)

    resp = client.get("/schueler/thema/testthema")
    body = resp.get_data(as_text=True)

    # 4 subtasks total, 1 is_intro -> denominator is 3, not 4
    assert "von 3 Aufgaben erledigt" in body
