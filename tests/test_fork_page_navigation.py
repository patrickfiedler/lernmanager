"""The fork page is a stop in the Thema, not a wall in front of it.

Patrick, 2026-09-14, Kl.6 „Mein digitaler Alltag": once E, 1 and 2 were done the
picker replaced every page -- clicking dot E reloaded ?aufgabe=1 and got the picker
again, so the earlier tasks were out of reach until the student chose. Wanted order:
E, 1, 2, 🔀 before the pick; E, 1, 2, 🔀, 3, 4, ... after it.
"""
import models


def _forked_task(app):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "forknav", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "6", "")

    base1 = models.create_subtask(task_id, "Basis 1", reihenfolge=1)
    base2 = models.create_subtask(task_id, "Basis 2", reihenfolge=2)
    a1 = models.create_subtask(task_id, "Branch A - 1", reihenfolge=3)
    b1 = models.create_subtask(task_id, "Branch B - 1", reihenfolge=4)

    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET fork_group='g1', fork_branch='a', "
                     "fork_branch_label='Weg A' WHERE id=?", (a1,))
        conn.execute("UPDATE subtask SET fork_group='g1', fork_branch='b', "
                     "fork_branch_label='Weg B' WHERE id=?", (b1,))

    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)).fetchone()["id"]
    ctx = {"student_id": student_id, "student_task_id": student_task_id,
           "base1": base1, "base2": base2, "a1": a1}
    return ctx


def _get(client, ctx, query=""):
    with client.session_transaction() as sess:
        sess["student_id"] = ctx["student_id"]
    return client.get("/schueler/thema/testthema" + query).get_data(as_text=True)


def _finish_base(ctx):
    for sid in (ctx["base1"], ctx["base2"]):
        models.toggle_student_subtask(ctx["student_task_id"], sid, True)


def test_earlier_task_reachable_while_picker_is_open(app, client):
    """The bug itself: base tasks done, no pick yet, dot 1 must show task 1."""
    ctx = _forked_task(app)
    _finish_base(ctx)

    assert "Wähle deinen Weg" in _get(client, ctx)          # landing still opens the picker
    body = _get(client, ctx, "?aufgabe=1")
    assert "Wähle deinen Weg" not in body
    assert "Basis 1" in body


def test_fork_page_reachable_before_the_base_is_done(app, client):
    """Branches can be previewed early; the buttons wait for the base tasks."""
    ctx = _forked_task(app)

    body = _get(client, ctx, "?weg=g1")
    assert "Wähle deinen Weg" in body
    assert "Weg A" in body
    assert "Weg A wählen" not in body


def test_fork_page_stays_after_the_pick(app, client):
    """After picking: the dot turns into a stop showing the pick, re-pick still open."""
    ctx = _forked_task(app)
    _finish_base(ctx)
    _get(client, ctx)                                       # logs the student in
    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={"branch": "a"})

    body = _get(client, ctx, "?weg=g1")
    assert "Dein Weg" in body
    assert "✅ Deine Wahl" in body
    assert "Weg B wählen" in body                           # not locked yet
    assert "dot-fork-pending" not in body

    models.toggle_student_subtask(ctx["student_task_id"], ctx["a1"], True)
    body = _get(client, ctx, "?weg=g1")
    assert "festgelegt" in body
    assert "Weg B wählen" not in body


def test_unknown_fork_group_falls_back_to_the_task(app, client):
    ctx = _forked_task(app)

    body = _get(client, ctx, "?weg=gibtsnicht")
    assert "Wähle deinen Weg" not in body
    assert "Basis 1" in body
