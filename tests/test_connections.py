"""Regression tests for Clayden-style unit Connections (unit_slug/connections_json
on task, models.get_looking_forward_to, import_task.py validation, admin round-trip).
"""
import json
import models
import import_task


def test_task_unit_slug_and_connections_round_trip(db):
    connections = {
        "building_on": [{"unit": "modul_00", "label": "Atombau (Sek I)", "strength": "hard"}],
        "arriving_at": ["Du kannst erklären, warum Metalle Strom leiten."],
    }
    task_id = models.create_task(
        "Atommodelle", "Beschreibung", "", "Chemie", "11/12", "pflicht",
        unit_slug="modul_01", connections_json=json.dumps(connections),
    )
    task = models.get_task(task_id)
    assert task["unit_slug"] == "modul_01"
    assert json.loads(task["connections_json"]) == connections

    models.update_task(
        task_id, "Atommodelle", "Beschreibung", "", "Chemie", "11/12", "pflicht",
        unit_slug="modul_01_renamed", connections_json=None,
    )
    task = models.get_task(task_id)
    assert task["unit_slug"] == "modul_01_renamed"
    assert task["connections_json"] is None


def test_get_task_by_unit_slug(db):
    task_id = models.create_task("X", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_x")
    assert models.get_task_by_unit_slug("modul_x")["id"] == task_id
    assert models.get_task_by_unit_slug("does_not_exist") is None
    assert models.get_task_by_unit_slug(None) is None


def test_looking_forward_to_computes_inverse_of_building_on(db):
    models.create_task("Atommodelle", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_01")
    models.create_task(
        "Redox", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_02",
        connections_json=json.dumps({"building_on": [{"unit": "modul_01", "label": "Atommodelle", "strength": "soft"}]}),
    )
    models.create_task(
        "Elektrolyse", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_12",
        connections_json=json.dumps({"building_on": [{"unit": "modul_01", "label": "Atommodelle", "strength": "hard"}]}),
    )
    # Unrelated task, should not show up
    models.create_task("Unrelated", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_99")

    result = models.get_looking_forward_to("modul_01")
    by_unit = {r["unit"]: r for r in result}
    assert set(by_unit) == {"modul_02", "modul_12"}
    assert by_unit["modul_02"]["strength"] == "soft"
    assert by_unit["modul_12"]["strength"] == "hard"


def test_looking_forward_to_empty_when_no_slug(db):
    assert models.get_looking_forward_to(None) == []
    assert models.get_looking_forward_to("") == []


def test_import_validates_unit_slug_format(db):
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "Chemie", "stufe": "11/12", "unit_slug": "Modul-01!"}}
    try:
        import_task.validate_task_structure(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "unit_slug" in str(e)


def test_import_validates_building_on_strength(db):
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "Chemie", "stufe": "11/12",
                      "connections": {"building_on": [{"label": "x", "strength": "medium"}]}}}
    try:
        import_task.validate_task_structure(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "strength" in str(e)


def test_import_warns_on_unresolved_building_on_unit(db):
    warnings = []
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "Chemie", "stufe": "11/12",
                      "connections": {"building_on": [{"unit": "does_not_exist", "label": "x"}]}}}
    import_task.validate_task_structure(data, warnings=warnings)  # should not raise
    assert any("does_not_exist" in w for w in warnings)


def test_import_creates_task_with_connections(db):
    data = {"task": {"name": "Atommodelle", "beschreibung": "x", "fach": "Chemie", "stufe": "11/12",
                      "unit_slug": "modul_01",
                      "connections": {"building_on": [{"label": "Sek-I-Vorkenntnisse"}],
                                      "arriving_at": ["Du kannst Flammenfarben erklären."]}}}
    import_task.validate_task_structure(data)
    task_id = import_task.import_task(data)
    task = models.get_task(task_id)
    assert task["unit_slug"] == "modul_01"
    assert json.loads(task["connections_json"])["arriving_at"] == ["Du kannst Flammenfarben erklären."]


def test_import_rejects_duplicate_unit_slug(db):
    models.create_task("Existing", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_01")
    data = {"task": {"name": "New Task", "beschreibung": "x", "fach": "Chemie", "stufe": "11/12", "unit_slug": "modul_01"}}
    try:
        import_task.import_task(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "modul_01" in str(e)


def test_student_klasse_page_renders_connections(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "connstest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task(
        "Atommodelle", "Beschreibung", "", "Chemie", "11/12", "pflicht",
        unit_slug="modul_01",
        connections_json=json.dumps({
            "building_on": [{"unit": "modul_00", "label": "Atombau (Sek I)", "strength": "hard"}],
            "arriving_at": ["Du kannst erklären, warum Metalle Strom leiten."],
        }),
    )
    models.create_subtask(task_id, "Erste Aufgabe", reihenfolge=0)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    models.create_task(
        "Redox", "x", "", "Chemie", "11/12", "pflicht", unit_slug="modul_02",
        connections_json=json.dumps({"building_on": [{"unit": "modul_01", "label": "Atommodelle", "strength": "hard"}]}),
    )

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.get("/schueler/thema/atommodelle")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Verbindungen" in body
    assert "Atombau (Sek I)" in body
    assert "Du kannst erklären, warum Metalle Strom leiten." in body
    assert "Redox" in body  # looking_forward_to


def test_student_klasse_page_hides_connections_box_when_empty(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test2", "Schueler", "connstest2", "pw123")
    klasse_id = models.create_klasse("Chemie12")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Plain Topic", "Beschreibung", "", "Chemie", "11/12", "pflicht")
    models.create_subtask(task_id, "Erste Aufgabe", reihenfolge=0)
    models.assign_task_to_student(student_id, klasse_id, task_id)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.get("/schueler/thema/plain-topic")
    assert resp.status_code == 200
    assert "Verbindungen" not in resp.get_data(as_text=True)


def test_admin_thema_form_creates_with_unit_slug(app, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    resp = as_admin.post("/admin/thema/neu", data={
        "name": "Atommodelle", "number": "1", "fach": "Chemie", "stufe": "11/12",
        "kategorie": "pflicht", "module_tier": "kern_standard",
        "lernziel": "", "beschreibung": "", "unit_slug": "modul_01",
    })
    assert resp.status_code == 302
    task = models.get_task_by_unit_slug("modul_01")
    assert task is not None


def test_admin_thema_bearbeiten_round_trips_connections_textareas(app, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    task_id = models.create_task("Atommodelle", "", "", "Chemie", "11/12", "pflicht")
    resp = as_admin.post(f"/admin/thema/{task_id}/bearbeiten", data={
        "name": "Atommodelle", "number": "1", "fach": "Chemie", "stufe": "11/12",
        "kategorie": "pflicht", "lernziel": "", "beschreibung": "",
        "module_tier": "kern_standard", "unit_slug": "modul_01",
        "building_on": "Atombau (Sek I) | modul_00 | hard\nReine Sek-I-Vorkenntnisse",
        "arriving_at": "Du kannst erklären, warum Metalle Strom leiten.",
    })
    assert resp.status_code == 302

    task = models.get_task(task_id)
    connections = json.loads(task["connections_json"])
    assert connections["building_on"] == [
        {"label": "Atombau (Sek I)", "unit": "modul_00", "strength": "hard"},
        {"label": "Reine Sek-I-Vorkenntnisse"},
    ]
    assert connections["arriving_at"] == ["Du kannst erklären, warum Metalle Strom leiten."]

    detail = as_admin.get(f"/admin/thema/{task_id}")
    body = detail.get_data(as_text=True)
    assert "Atombau (Sek I) | modul_00 | hard" in body


def test_admin_thema_bearbeiten_rejects_duplicate_unit_slug(app, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    models.create_task("Existing", "", "", "Chemie", "11/12", "pflicht", unit_slug="modul_01")
    other_id = models.create_task("Other", "", "", "Chemie", "11/12", "pflicht")
    resp = as_admin.post(f"/admin/thema/{other_id}/bearbeiten", data={
        "name": "Other", "number": "1", "fach": "Chemie", "stufe": "11/12",
        "kategorie": "pflicht", "lernziel": "", "beschreibung": "",
        "module_tier": "kern_standard", "unit_slug": "modul_01",
    })
    assert resp.status_code == 302
    other = models.get_task(other_id)
    assert other["unit_slug"] is None
