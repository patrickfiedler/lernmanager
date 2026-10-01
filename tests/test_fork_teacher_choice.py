"""For a Seilbahn student the teacher picks the fork branch (models.is_fork_teacher_choice).

No picker on the topic page, a set branch is fixed at once (not only after the first
finished task), and the admin pages let the teacher set the first branch and tell
them that one is missing.

Request: docs/shared/requests/2026-08-31-mbi-akutfall-behoben-systemfrage-offen-kein-datenvertrag.md, point 5
Regular students: tests/test_fork_choice_e2e.py
"""
import models


def _setup(app, lernpfad='seilbahn'):
    """Thema: Basis 1 -> Verzweigung g1 (Weg A | Weg B) -> Nach dem Fork. Basis 1 is done."""
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "forktest", "pw123", lernpfad=lernpfad)
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "")
    path = 'seilbahn' if lernpfad == 'seilbahn' else None
    base1 = models.create_subtask(task_id, "Basis 1", reihenfolge=1, path=path)
    a1 = models.create_subtask(task_id, "Branch A - 1", reihenfolge=2, path=path,
                               fork_group='g1', fork_branch='a', fork_branch_label='Weg A')
    models.create_subtask(task_id, "Branch B - 1", reihenfolge=2, path=path,
                          fork_group='g1', fork_branch='b', fork_branch_label='Weg B')
    models.create_subtask(task_id, "Nach dem Fork", reihenfolge=3, path=path)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)).fetchone()['id']
    models.toggle_student_subtask(student_task_id, base1, True)
    return {'student_id': student_id, 'klasse_id': klasse_id, 'task_id': task_id, 'a1': a1}


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_open_fork_shows_no_picker(app, client):
    ctx = _setup(app)
    _login(client, ctx['student_id'])
    body = client.get("/schueler/thema/testthema").get_data(as_text=True)

    assert "Deine Lehrperson wählt deinen Weg." in body
    assert "Wähle deinen Weg" not in body
    assert "/fork/g1/waehlen" not in body
    assert "Weg A" not in body and "Weg B" not in body


def test_student_cannot_pick_by_hand_built_request(app, client):
    ctx = _setup(app)
    _login(client, ctx['student_id'])
    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={'branch': 'a'})
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') is None


def test_set_branch_is_fixed_at_once(app, client):
    """Nothing in the branch is done yet -- a regular student could still switch."""
    ctx = _setup(app)
    models.set_student_fork_choice(ctx['student_id'], 'g1', 'a')
    _login(client, ctx['student_id'])

    body = client.get("/schueler/thema/testthema?weg=g1").get_data(as_text=True)
    assert "Dein Weg ist <strong>Weg A</strong>" in body
    assert "/fork/g1/waehlen" not in body
    assert "Weg B" not in body

    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={'branch': 'b'})
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') == 'a'


def test_regular_student_still_picks(app, client):
    ctx = _setup(app, lernpfad='bergweg')
    _login(client, ctx['student_id'])
    body = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert "Wähle deinen Weg" in body
    assert "Deine Lehrperson wählt" not in body

    client.post("/schueler/thema/testthema/fork/g1/waehlen", data={'branch': 'a'})
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') == 'a'


def test_teacher_sets_the_first_branch(app, as_admin):
    ctx = _setup(app)
    sid = ctx['student_id']

    assert [(c['fork_group'], c['fork_branch']) for c in models.get_student_fork_choices(sid)] == [('g1', None)]
    html = as_admin.get(f"/admin/schueler/{sid}").get_data(as_text=True)
    assert "noch kein Zweig" in html
    assert "Zweig setzen" in html

    as_admin.post(f"/admin/schueler/{sid}/fork-zweig",
                  data={'fork_group': 'g1', 'branch': 'b', 'task_id': ctx['task_id']})
    assert models.get_student_fork_choice(sid, 'g1') == 'b'
    assert [(c['fork_group'], c['fork_branch']) for c in models.get_student_fork_choices(sid)] == [('g1', 'b')]


def test_class_page_lists_seilbahn_student_without_branch(app, as_admin):
    ctx = _setup(app)
    kid = ctx['klasse_id']

    assert [s['zweig_fehlt'] for s in models.get_students_in_klasse(kid)] == [1]
    assert "1 Seilbahn-Schüler ohne Zweig" in as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)

    models.set_student_fork_choice(ctx['student_id'], 'g1', 'a')
    assert [s['zweig_fehlt'] for s in models.get_students_in_klasse(kid)] == [0]
    assert "ohne Zweig" not in as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)


def test_class_page_is_quiet_for_a_regular_student_without_branch(app, as_admin):
    ctx = _setup(app, lernpfad='bergweg')
    assert [s['zweig_fehlt'] for s in models.get_students_in_klasse(ctx['klasse_id'])] == [0]
