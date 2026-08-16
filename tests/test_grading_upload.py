"""Tests for sub-phase 2f: the admin upload page's supporting model
functions and routes (task/rubric picker, manifest builder, health check,
job-registration endpoint, nginx auth-check gate).
"""
import json
import re

import config
import models


def _csrf_token(client):
    """Extract the csrf-token meta tag from any rendered page, same as the
    real upload page's JS does -- exercises the actual CSRF-protected path
    instead of bypassing it."""
    resp = client.get('/admin')
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1)


def _task_with_graded_artifact(keyword="unit-3-bilder-entdecken", reihenfolge=1):
    task_id = models.create_task("Bilder entdecken", "desc", "lz", "MBI", "6", "pflicht")
    models.create_subtask(
        task_id, "Aufgabe 1", reihenfolge=reihenfolge,
        graded_artifact_json=json.dumps({"keyword": keyword, "format": [".pptx"], "criteria": ["a"]}),
    )
    return task_id


def test_get_task_grading_keyword_returns_latest_subtasks_keyword(db):
    task_id = models.create_task("Bilder entdecken", "desc", "lz", "MBI", "6", "pflicht")
    models.create_subtask(task_id, "Aufgabe 1", reihenfolge=1,
                           graded_artifact_json=json.dumps({"keyword": "unit-3-bilder-entdecken"}))
    models.create_subtask(task_id, "Aufgabe 2", reihenfolge=2,
                           graded_artifact_json=json.dumps({"keyword": "unit-3-bilder-entdecken"}))
    assert models.get_task_grading_keyword(task_id) == "unit-3-bilder-entdecken"


def test_get_task_grading_keyword_none_when_no_graded_artifact(db):
    task_id = models.create_task("Plain unit", "desc", "lz", "MBI", "6", "pflicht")
    models.create_subtask(task_id, "Aufgabe 1", reihenfolge=1)
    assert models.get_task_grading_keyword(task_id) is None


def test_list_tasks_with_graded_artifact_excludes_plain_tasks(db):
    graded_id = _task_with_graded_artifact()
    plain_id = models.create_task("Plain unit", "desc", "lz", "MBI", "6", "pflicht")
    models.create_subtask(plain_id, "Aufgabe 1", reihenfolge=1)

    ids = {t["id"] for t in models.list_tasks_with_graded_artifact()}
    assert graded_id in ids
    assert plain_id not in ids


def test_build_grading_manifest_splits_matched_and_unmatched(db):
    klasse_id = models.create_klasse("6a")
    s1 = models.create_student("Mueller", "Anna", "u1", "pw", netzwerk_id="mueller.anna")
    s2 = models.create_student("Ohne", "Id", "u2", "pw")  # no netzwerk_id
    models.add_student_to_klasse(s1, klasse_id)
    models.add_student_to_klasse(s2, klasse_id)

    manifest, unmatched = models.build_grading_manifest(klasse_id)

    assert manifest["klasse"] == "6a"
    assert manifest["students"] == [{"login": "mueller.anna", "names": ["Anna", "Mueller"], "lernpfad": "bergweg"}]
    assert unmatched == [{"nachname": "Ohne", "vorname": "Id"}]


def test_health_route_reports_not_configured_when_url_empty(app, client, as_admin):
    config.GRADING_SERVICE_URL = ""
    resp = as_admin.get('/admin/grading/health')
    assert resp.status_code == 200
    assert resp.get_json() == {"configured": False, "online": False}


def test_health_route_reports_offline_when_unreachable(app, client, as_admin):
    config.GRADING_SERVICE_URL = "http://127.0.0.1:1"  # nothing listens here
    resp = as_admin.get('/admin/grading/health')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["configured"] is True
    assert body["online"] is False


def test_upload_page_requires_admin(app, client):
    klasse_id = models.create_klasse("6a")
    resp = client.get(f'/admin/klasse/{klasse_id}/grading/upload')
    assert resp.status_code in (302, 401, 403)


def test_upload_page_renders_task_picker_and_manifest(app, client, as_admin):
    klasse_id = models.create_klasse("6a")
    task_id = _task_with_graded_artifact()
    student_id = models.create_student("Mueller", "Anna", "muanna", "pw", netzwerk_id="mueller.anna")
    models.add_student_to_klasse(student_id, klasse_id)

    resp = as_admin.get(f'/admin/klasse/{klasse_id}/grading/upload')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "unit-3-bilder-entdecken" in body
    assert "mueller.anna" in body  # embedded manifest


def test_upload_page_manifest_escapes_script_breakout(app, client, as_admin):
    """
    The manifest is embedded via Jinja's |tojson filter (not json.dumps + |safe),
    which HTML-escapes '<', '>', '&' so a crafted student name can't close the
    <script> tag early and inject markup into an admin's session (finding #10).
    """
    klasse_id = models.create_klasse("6a")
    student_id = models.create_student(
        "</script><script>alert(1)</script>", "Anna", "hacker1", "pw",
        netzwerk_id="hacker.anna",
    )
    models.add_student_to_klasse(student_id, klasse_id)

    resp = as_admin.get(f'/admin/klasse/{klasse_id}/grading/upload')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "</script><script>alert(1)</script>" not in body
    assert "\\u003c/script\\u003e" in body


def test_upload_complete_creates_grading_run(app, client, as_admin):
    klasse_id = models.create_klasse("6a")
    task_id = _task_with_graded_artifact()
    token = _csrf_token(as_admin)

    resp = as_admin.post(
        f'/admin/klasse/{klasse_id}/grading/upload/complete',
        json={"job_id": "job-xyz", "task_id": task_id, "rubric": "unit-3-bilder-entdecken",
              "provider": "ollama", "students": 5},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 201, resp.get_json()
    run = models.get_grading_run_by_job_id("job-xyz")
    assert run is not None
    assert run["klasse_id"] == klasse_id
    assert run["task_id"] == task_id


def test_upload_complete_missing_fields_rejected(app, client, as_admin):
    klasse_id = models.create_klasse("6a")
    token = _csrf_token(as_admin)
    resp = as_admin.post(
        f'/admin/klasse/{klasse_id}/grading/upload/complete',
        json={"job_id": "x"}, headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 400


def test_internal_auth_check_requires_session(app, client):
    resp = client.get('/internal/auth-check')
    assert resp.status_code == 401


def test_internal_auth_check_passes_for_admin_session(app, client, as_admin):
    resp = as_admin.get('/internal/auth-check')
    assert resp.status_code == 204
