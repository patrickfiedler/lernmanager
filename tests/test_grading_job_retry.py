"""Tests for the grading-service job status/retry surface added on top of
grading_run_detail (grading-service-deployment.md §4 `POST /jobs/<id>/retry`,
2026-08-18). urllib.request.urlopen is mocked; no real network -- same
pattern as tests/test_grading_media_copy.py.
"""
import re
from unittest.mock import patch

import config
import models


def _csrf_token(client):
    resp = client.get('/admin')
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1)


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _setup(job_id="job-retry", graded_at=None):
    klasse_id = models.create_klasse("6a")
    task_id = models.create_task("unit-3-bilder-entdecken", "desc", "lz", "MBI", "6", "pflicht")
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    if graded_at:
        with models.db_session() as conn:
            conn.execute("UPDATE grading_run SET graded_at = ? WHERE id = ?", (graded_at, run_id))
    return run_id


def test_detail_page_shows_failed_status_and_retry_button(app, client, as_admin):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    run_id = _setup()

    status_json = b'{"status": "failed", "error": "OVH timeout"}'
    with patch("app.urllib.request.urlopen", return_value=_FakeResponse(status_json)):
        resp = as_admin.get(f'/admin/grading-run/{run_id}')

    body = resp.get_data(as_text=True)
    assert "fehlgeschlagen" in body
    assert "OVH timeout" in body
    assert "Erneut versuchen" in body


def test_detail_page_does_not_poll_once_graded(app, client, as_admin):
    run_id = _setup(graded_at="2026-08-18 10:00:00")

    with patch("app.urllib.request.urlopen") as mock_open:
        resp = as_admin.get(f'/admin/grading-run/{run_id}')

    mock_open.assert_not_called()
    assert resp.status_code == 200


def test_detail_page_shows_offline_when_service_unreachable(app, client, as_admin):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    run_id = _setup()

    with patch("app.urllib.request.urlopen", side_effect=OSError("unreachable")):
        resp = as_admin.get(f'/admin/grading-run/{run_id}')

    assert "nicht erreichbar" in resp.get_data(as_text=True)


def test_retry_route_requires_admin(app, client):
    run_id = _setup()
    resp = client.post(f'/admin/grading-run/{run_id}/retry-job')
    assert resp.status_code in (302, 401, 403)


def test_retry_route_success_flashes_and_redirects(app, client, as_admin):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    run_id = _setup()

    token = _csrf_token(as_admin)
    with patch("app.urllib.request.urlopen", return_value=_FakeResponse(b'{"job_id": "job-retry", "status": "queued"}')):
        resp = as_admin.post(f'/admin/grading-run/{run_id}/retry-job',
                              data={"csrf_token": token}, follow_redirects=True)

    assert resp.status_code == 200
    assert "Warteschlange" in resp.get_data(as_text=True)


def test_retry_route_409_shows_stale_state_message(app, client, as_admin):
    import urllib.error
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    run_id = _setup()

    token = _csrf_token(as_admin)
    err = urllib.error.HTTPError("url", 409, "Conflict", None, None)
    with patch("app.urllib.request.urlopen", side_effect=err):
        resp = as_admin.post(f'/admin/grading-run/{run_id}/retry-job',
                              data={"csrf_token": token}, follow_redirects=True)

    assert "nicht mehr im Status" in resp.get_data(as_text=True)
