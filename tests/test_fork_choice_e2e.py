"""End-to-end regression tests for the Fork/Choice selection screen (routes + template).

Design: docs/shared/lernmanager/fork-choice-artifact-model.md
Model-layer coverage: tests/test_fork_choice.py
"""
import models


def _setup_forked_task(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "forktest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "")

    base1 = models.create_subtask(task_id, "Basis 1", reihenfolge=1)
    a1 = models.create_subtask(task_id, "Branch A - 1", reihenfolge=2)
    b1 = models.create_subtask(task_id, "Branch B - 1", reihenfolge=2)
    after1 = models.create_subtask(task_id, "Nach dem Fork", reihenfolge=3)

    with models.db_session() as conn:
        conn.execute(
            "UPDATE subtask SET fork_group='g1', fork_branch='a', fork_branch_label='Weg A', fork_branch_note='Etwas Text zu A.' WHERE id=?",
            (a1,)
        )
        conn.execute(
            "UPDATE subtask SET fork_group='g1', fork_branch='b', fork_branch_label='Weg B' WHERE id=?",
            (b1,)
        )

    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)
        ).fetchone()['id']

    return {
        'student_id': student_id, 'task_id': task_id, 'student_task_id': student_task_id,
        'base1': base1, 'a1': a1, 'b1': b1, 'after1': after1,
    }


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_picker_shown_once_prior_subtask_done(app, client):
    ctx = _setup_forked_task(app)
    _login(client, ctx['student_id'])

    # Not reached yet: base1 undone, normal subtask content shows.
    resp = client.get("/schueler/thema/testthema")
    assert b"W\xc3\xa4hle deinen Weg" not in resp.data

    models.toggle_student_subtask(ctx['student_task_id'], ctx['base1'], True)

    resp = client.get("/schueler/thema/testthema")
    body = resp.get_data(as_text=True)
    assert "Wähle deinen Weg" in body
    assert "Weg A" in body
    assert "Weg B" in body
    assert "Etwas Text zu A." in body


def test_choosing_branch_reveals_its_subtasks(app, client):
    ctx = _setup_forked_task(app)
    _login(client, ctx['student_id'])
    models.toggle_student_subtask(ctx['student_task_id'], ctx['base1'], True)

    resp = client.post("/schueler/thema/testthema/fork/g1/waehlen", data={"branch": "a"})
    assert resp.status_code == 302
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') == 'a'

    resp = client.get("/schueler/thema/testthema")
    body = resp.get_data(as_text=True)
    assert "Wähle deinen Weg" not in body
    assert "Branch A - 1" in body


def test_invalid_branch_rejected(app, client):
    ctx = _setup_forked_task(app)
    _login(client, ctx['student_id'])
    models.toggle_student_subtask(ctx['student_task_id'], ctx['base1'], True)

    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={"branch": "does-not-exist"})
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') is None


def test_repick_blocked_after_lock(app, client):
    ctx = _setup_forked_task(app)
    _login(client, ctx['student_id'])
    models.toggle_student_subtask(ctx['student_task_id'], ctx['base1'], True)

    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={"branch": "a"})
    models.toggle_student_subtask(ctx['student_task_id'], ctx['a1'], True)

    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={"branch": "b"})
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') == 'a'
