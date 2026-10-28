"""Staff looks at the student pages (app.py, Student Preview).

A real student is read-only: POSTs are refused, GET writes are rolled back. A
teacher may only preview a student who sits in none but her classes.
"""
import pytest
from flask import g

import models


@pytest.fixture
def setup(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse = models.create_klasse("7a")
    student = models.create_student("Muster", "Max", "maxmuster", "x")
    models.add_student_to_klasse(student, klasse)
    task = models.create_task("Thema A", "", "", "MBI", "7", "pflicht")
    models.create_subtask(task, "### Eins", reihenfolge=0)
    models.assign_task_to_student(student, klasse, task)
    return {'klasse': klasse, 'student': student, 'task': task}


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = 1
    return client


def test_preview_shows_student_pages_with_banner(app, setup):
    client = _admin_client(app)
    resp = client.post(f"/admin/schueler/{setup['student']}/vorschau")
    assert resp.status_code == 302
    page = client.get("/schueler").get_data(as_text=True)
    assert "Vorschau als" in page and "nichts wird gespeichert" in page
    assert "Vorschau beenden" in page


def test_preview_refuses_writes(app, setup):
    client = _admin_client(app)
    client.post(f"/admin/schueler/{setup['student']}/vorschau")
    resp = client.post("/schueler/thema/thema-a/aufgabe/1", json={"erledigt": True})
    assert resp.status_code == 403
    with models.db_session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM student_subtask WHERE erledigt = 1").fetchone()[0] == 0


def test_read_only_request_rolls_back(app, setup):
    with app.test_request_context():
        g.read_only = True
        with models.db_session() as conn:
            conn.execute("UPDATE student SET vorname = 'Geändert'")
    assert models.get_student(setup['student'])['vorname'] == 'Max'


def test_end_preview_returns_to_admin(app, setup):
    client = _admin_client(app)
    client.post(f"/admin/schueler/{setup['student']}/vorschau")
    resp = client.get("/vorschau/beenden")
    assert f"/admin/schueler/{setup['student']}" in resp.headers['Location']
    with client.session_transaction() as sess:
        assert 'student_id' not in sess and 'preview_student_id' not in sess
    assert client.get("/admin/klassen").status_code == 200


def test_teacher_preview_only_students_without_foreign_class(app, setup):
    models.create_admin("lehrerin", "testpass", role="teacher")
    teacher = models.verify_admin("lehrerin", "testpass")
    models.add_teacher_to_klasse(teacher['id'], setup['klasse'])
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = teacher['id']
    assert client.post(f"/admin/schueler/{setup['student']}/vorschau").status_code == 302

    # Same student also sits in a class she does not teach: the student pages
    # would show that class's topics too.
    models.add_student_to_klasse(setup['student'], models.create_klasse("Fremde"))
    assert client.post(f"/admin/schueler/{setup['student']}/vorschau").status_code == 404


def test_sandbox_student_is_writable_and_reused(app, setup):
    client = _admin_client(app)
    client.post("/admin/vorschau-schueler")
    with client.session_transaction() as sess:
        sandbox = sess['student_id']
    assert models.is_preview_student_of(sandbox, 1)
    klasse = models.get_student_klassen(sandbox)[0]
    assert klasse['name'] == 'Vorschau – admin'

    # Topics are assigned in the sandbox class like anywhere else; ticks are kept.
    models.assign_task_to_student(sandbox, klasse['id'], setup['task'])
    page = client.get("/schueler").get_data(as_text=True)
    assert "alles wird gespeichert" in page
    resp = client.post("/schueler/thema/thema-a/aufgabe/1", json={"erledigt": True})
    assert resp.status_code == 200

    client.get("/vorschau/beenden")
    client.post("/admin/vorschau-schueler")
    with client.session_transaction() as sess:
        assert sess['student_id'] == sandbox
    assert len(models.get_student_klassen(sandbox)) == 1


def test_someone_elses_sandbox_is_read_only(app, setup):
    models.create_admin("lehrerin", "testpass", role="teacher")
    teacher = models.verify_admin("lehrerin", "testpass")
    sandbox = models.get_or_create_preview_student(teacher['id'], 'lehrerin')
    client = _admin_client(app)
    client.post(f"/admin/schueler/{sandbox}/vorschau")
    assert "nichts wird gespeichert" in client.get("/schueler").get_data(as_text=True)

