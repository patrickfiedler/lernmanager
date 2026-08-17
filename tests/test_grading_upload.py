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


def test_get_task_by_grading_keyword_resolves_unique_match(db):
    task_id = _task_with_graded_artifact(keyword="unit-3-bilder-entdecken")
    assert models.get_task_by_grading_keyword("unit-3-bilder-entdecken") == task_id


def test_get_task_by_grading_keyword_none_when_no_match(db):
    _task_with_graded_artifact(keyword="unit-3-bilder-entdecken")
    assert models.get_task_by_grading_keyword("no-such-rubric") is None


def test_get_task_by_grading_keyword_none_when_ambiguous(db):
    """Two tasks sharing a rubric keyword must not be guessed at --
    auto-create (import_grading_callback) would misroute grades onto the
    wrong task otherwise."""
    _task_with_graded_artifact(keyword="shared-keyword")
    _task_with_graded_artifact(keyword="shared-keyword")
    assert models.get_task_by_grading_keyword("shared-keyword") is None


def test_match_netzwerk_logins_returns_only_matches(db):
    klasse_id = models.create_klasse("6a")
    s1 = models.create_student("Mueller", "Anna", "u1", "pw", netzwerk_id="mueller.anna")
    models.add_student_to_klasse(s1, klasse_id)

    matches = models.match_netzwerk_logins(["mueller.anna", "unknown.folder"])

    assert matches == [{"login": "mueller.anna", "names": ["Anna", "Mueller"], "lernpfad": "bergweg"}]


def test_match_netzwerk_logins_spans_multiple_classes(db):
    """The whole point of the redesign: matching is global, not scoped to
    one class -- a zip can contain students from several classes at once."""
    k1 = models.create_klasse("6a")
    k2 = models.create_klasse("6b")
    s1 = models.create_student("Mueller", "Anna", "u1", "pw", netzwerk_id="mueller.anna")
    s2 = models.create_student("Schmidt", "Ben", "u2", "pw", netzwerk_id="schmidt.ben")
    models.add_student_to_klasse(s1, k1)
    models.add_student_to_klasse(s2, k2)

    matches = models.match_netzwerk_logins(["mueller.anna", "schmidt.ben"])
    logins = {m["login"] for m in matches}
    assert logins == {"mueller.anna", "schmidt.ben"}


def test_match_netzwerk_logins_empty_input(db):
    assert models.match_netzwerk_logins([]) == []


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
    resp = client.get('/admin/grading/upload')
    assert resp.status_code in (302, 401, 403)


def test_upload_page_renders_task_picker(app, client, as_admin):
    _task_with_graded_artifact()

    resp = as_admin.get('/admin/grading/upload')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "unit-3-bilder-entdecken" in body
    # No manifest/roster embedded anymore -- the page resolves logins found
    # in the client-parsed zip via /admin/grading/match-logins instead.
    assert "grading-manifest" not in body


def test_match_logins_route_requires_admin(app, client):
    resp = client.post('/admin/grading/match-logins', json={"logins": []})
    assert resp.status_code in (302, 401, 403)


def test_match_logins_route_returns_matches_and_unmatched(app, client, as_admin):
    klasse_id = models.create_klasse("6a")
    student_id = models.create_student("Mueller", "Anna", "muanna", "pw", netzwerk_id="mueller.anna")
    models.add_student_to_klasse(student_id, klasse_id)
    token = _csrf_token(as_admin)

    resp = as_admin.post(
        '/admin/grading/match-logins',
        json={"logins": ["mueller.anna", "unknown.folder"]},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["matches"] == [{"login": "mueller.anna", "names": ["Anna", "Mueller"], "lernpfad": "bergweg"}]
    assert data["unmatched"] == ["unknown.folder"]


def test_match_logins_route_rejects_non_list_payload(app, client, as_admin):
    token = _csrf_token(as_admin)
    resp = as_admin.post(
        '/admin/grading/match-logins', json={"logins": "not-a-list"},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 400


def test_upload_complete_creates_grading_run(app, client, as_admin):
    task_id = _task_with_graded_artifact()
    token = _csrf_token(as_admin)

    resp = as_admin.post(
        '/admin/grading/upload/complete',
        json={"job_id": "job-xyz", "task_id": task_id, "rubric": "unit-3-bilder-entdecken",
              "provider": "ollama", "students": 5},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 201, resp.get_json()
    run = models.get_grading_run_by_job_id("job-xyz")
    assert run is not None
    assert run["klasse_id"] is None  # a run can now span several classes
    assert run["task_id"] == task_id


def test_upload_complete_missing_fields_rejected(app, client, as_admin):
    token = _csrf_token(as_admin)
    resp = as_admin.post(
        '/admin/grading/upload/complete',
        json={"job_id": "x"}, headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 400


def test_internal_auth_check_requires_session(app, client):
    resp = client.get('/internal/auth-check')
    assert resp.status_code == 401


def test_internal_auth_check_passes_for_admin_session(app, client, as_admin):
    resp = as_admin.get('/internal/auth-check')
    assert resp.status_code == 204
