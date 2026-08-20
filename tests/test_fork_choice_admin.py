"""Regression tests for the Fork/Choice admin editor fields (thema_detail.html save path)."""
import models


def test_saving_subtasks_persists_fork_fields(app, client, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    task_id = models.create_task("Adminthema", "", "", "MBI", "5/6", "")
    models.create_subtask(task_id, "Basis", reihenfolge=0)
    models.create_subtask(task_id, "Zweig A", reihenfolge=1)

    resp = as_admin.post(f"/admin/thema/{task_id}/aufgaben", data={
        "subtasks[]": ["Basis", "Zweig A"],
        "estimated_minutes[]": ["", ""],
        "quiz_json[]": ["", ""],
        "path[]": ["", ""],
        "path_model[]": ["skip", "skip"],
        "fertig_wenn[]": ["", ""],
        "tipps[]": ["", ""],
        "checkpoint_type[]": ["", ""],
        "kern_standard_tag[]": ["", ""],
        "checkpoint_hints[]": ["", ""],
        "school_only[]": ["0", "0"],
        "fork_group[]": ["", "g1"],
        "fork_branch[]": ["", "a"],
        "fork_branch_label[]": ["", "Weg A"],
        "fork_branch_note[]": ["", "Ein Hinweistext."],
        "fork_required[]": ["1", "0"],
    })
    assert resp.status_code == 302

    subtasks = models.get_subtasks(task_id)
    by_desc = {s["beschreibung"]: s for s in subtasks}
    assert by_desc["Basis"]["fork_group"] is None
    zweig = by_desc["Zweig A"]
    assert zweig["fork_group"] == "g1"
    assert zweig["fork_branch"] == "a"
    assert zweig["fork_branch_label"] == "Weg A"
    assert zweig["fork_branch_note"] == "Ein Hinweistext."
    assert zweig["fork_required"] == 0


def _setup_chosen_fork():
    student_id = models.create_student("Test", "Schueler", "forkadmintest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Reassignthema", "", "", "MBI", "5/6", "")
    a1 = models.create_subtask(task_id, "Weg A", reihenfolge=1)
    b1 = models.create_subtask(task_id, "Weg B", reihenfolge=1)
    with models.db_session() as conn:
        conn.execute(
            "UPDATE subtask SET fork_group='g1', fork_branch='a', fork_branch_label='Weg A' WHERE id=?", (a1,)
        )
        conn.execute(
            "UPDATE subtask SET fork_group='g1', fork_branch='b', fork_branch_label='Weg B' WHERE id=?", (b1,)
        )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    models.set_student_fork_choice(student_id, 'g1', 'a')
    return student_id, task_id


def test_student_detail_shows_fork_choice(app, client, as_admin):
    student_id, _ = _setup_chosen_fork()
    resp = as_admin.get(f"/admin/schueler/{student_id}")
    body = resp.get_data(as_text=True)
    assert "Verzweigungs-Wahl" in body
    assert "Reassignthema" in body


def test_teacher_can_reassign_fork_choice(app, client, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id, task_id = _setup_chosen_fork()

    resp = as_admin.post(f"/admin/schueler/{student_id}/fork-zweig", data={
        "fork_group": "g1", "task_id": task_id, "branch": "b",
    })
    assert resp.status_code == 302
    assert models.get_student_fork_choice(student_id, 'g1') == 'b'


def test_fork_group_without_branch_rejected(app, client, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    task_id = models.create_task("Adminthema2", "", "", "MBI", "5/6", "")
    models.create_subtask(task_id, "Basis", reihenfolge=0)

    resp = as_admin.post(f"/admin/thema/{task_id}/aufgaben", data={
        "subtasks[]": ["Basis"],
        "fork_group[]": ["g1"],
        "fork_branch[]": [""],
    }, follow_redirects=True)

    assert "müssen beide oder keins ausgefüllt sein" in resp.get_data(as_text=True)
    subtasks = models.get_subtasks(task_id)
    assert subtasks[0]["fork_group"] is None
