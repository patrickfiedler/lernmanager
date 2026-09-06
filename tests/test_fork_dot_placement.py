"""Exactly one placeholder dot per pending fork group.

Patrick, 2026-09-06, from a production screenshot of Kl.6 „Mein digitaler Alltag":
two identical orange fork icons side by side, neither of them interactive.

Both came from the same group. The dot is emitted in two places -- inside the
subtask loop (`loop.index in pending_fork_dot_positions`) and once after it
(`subtasks|length in ...`) -- and for a fork that sits after every visible subtask
those two conditions are the same condition. Every existing fork test happens to
put a subtask AFTER the fork, so the overlap never showed up.
"""
import models


def _forked_task(app, trailing_subtask):
    """A fork group whose branches are the last subtasks, unless trailing_subtask."""
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "forkdot", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "6", "")

    base1 = models.create_subtask(task_id, "Basis 1", reihenfolge=1)
    a1 = models.create_subtask(task_id, "Branch A - 1", reihenfolge=2)
    b1 = models.create_subtask(task_id, "Branch B - 1", reihenfolge=3)
    if trailing_subtask:
        models.create_subtask(task_id, "Nach dem Fork", reihenfolge=4)

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
    return {"student_id": student_id, "student_task_id": student_task_id, "base1": base1}


def _body(client, ctx):
    with client.session_transaction() as sess:
        sess["student_id"] = ctx["student_id"]
    return client.get("/schueler/thema/testthema").get_data(as_text=True)


def _dots(client, ctx):
    return _body(client, ctx).count("dot-fork-pending")


def test_a_fork_after_the_last_subtask_draws_one_dot(app, client):
    """The production case: nothing follows the branches."""
    assert _dots(client, _forked_task(app, trailing_subtask=False)) == 1


def test_a_fork_between_subtasks_still_draws_one_dot(app, client):
    """The case the existing tests already covered -- must not regress."""
    assert _dots(client, _forked_task(app, trailing_subtask=True)) == 1


def test_a_locked_fork_says_what_is_missing(app, client):
    """The other half of the same screenshot: the icon was not only doubled, it was
    mute. Nothing on the page said the choice needed the earlier tasks first, so the
    fork read as broken rather than as not-yet-reached."""
    ctx = _forked_task(app, trailing_subtask=False)

    body = _body(client, ctx)
    assert "Gleich darfst du wählen" in body
    assert "eine Aufgabe" in body
    assert "Wähle deinen Weg" not in body

    models.toggle_student_subtask(ctx["student_task_id"], ctx["base1"], True)

    body = _body(client, ctx)
    assert "Gleich darfst du wählen" not in body
    assert "Wähle deinen Weg" in body
