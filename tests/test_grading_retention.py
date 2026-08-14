"""Tests for sub-phase 2i: supersede compare page + retention/purge wiring."""
import os
import re
from unittest.mock import patch

import config
import models


def _csrf_token(client):
    resp = client.get('/admin')
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1)


def _setup(job_id="job-ret"):
    klasse_id = models.create_klasse("6a")
    task_id = models.create_task("unit-3-bilder-entdecken", "desc", "lz", "MBI", "6", "pflicht")
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    return klasse_id, task_id, run_id


def _student(nachname, vorname, netzwerk_id):
    return models.create_student(nachname, vorname, f"u{netzwerk_id}", "pw", netzwerk_id=netzwerk_id)


def test_is_grading_run_settled(db):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("A", "A", "a.a")
    r1 = models.create_grading_result(run_id, task_id, s1, "a.a", [{"name": "X", "score": 1, "max_score": 1}])
    assert models.is_grading_run_settled(run_id) is False
    models.discard_grading_result(r1)
    assert models.is_grading_run_settled(run_id) is True


def test_purge_grading_run_media_deletes_local_dir_and_marks(tmp_path, db):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = ""
    klasse_id, task_id, run_id = _setup()

    media_dir = os.path.join(str(tmp_path), "grading", str(run_id))
    os.makedirs(media_dir, exist_ok=True)
    with open(os.path.join(media_dir, "test.jpg"), "wb") as f:
        f.write(b"data")

    models.purge_grading_run_media(run_id)

    assert not os.path.isdir(media_dir)
    assert models.get_grading_run(run_id)["media_purged_at"] is not None


def test_purge_calls_grading_service_delete(tmp_path, db):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "tok"
    klasse_id, task_id, run_id = _setup()

    with patch("models.urllib.request.urlopen") as mock_open:
        models.purge_grading_run_media(run_id)
    called_req = mock_open.call_args[0][0]
    assert called_req.get_method() == "DELETE"
    assert called_req.full_url == f"http://10.8.0.3:8420/jobs/job-ret"


def test_purge_is_resilient_to_service_errors(tmp_path, db):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    klasse_id, task_id, run_id = _setup()

    with patch("models.urllib.request.urlopen", side_effect=OSError("offline")):
        models.purge_grading_run_media(run_id)  # must not raise
    assert models.get_grading_run(run_id)["media_purged_at"] is not None


def test_auto_purge_only_fires_once_settled(tmp_path, db):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = ""
    klasse_id, task_id, run_id = _setup()
    s1 = _student("A", "A", "a.a")
    r1 = models.create_grading_result(run_id, task_id, s1, "a.a", [{"name": "X", "score": 1, "max_score": 1}])

    models.maybe_auto_purge_grading_run(run_id)
    assert models.get_grading_run(run_id)["media_purged_at"] is None  # still under review

    models.discard_grading_result(r1)
    models.maybe_auto_purge_grading_run(run_id)
    assert models.get_grading_run(run_id)["media_purged_at"] is not None


def test_supersede_route_challenger_wins(app, client, as_admin, tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = ""
    klasse_id, task_id, run1 = _setup(job_id="job-ret-1")
    s1 = _student("Mueller", "Anna", "mueller.anna")
    active_id = models.create_grading_result(run1, task_id, s1, "mueller.anna",
                                              [{"name": "X", "score": 1, "max_score": 1}])
    models.release_grading_result(active_id, models.create_admin("prior", "pw"))

    # Second run against the SAME task -- a supersede conflict is always two
    # runs targeting one (student, artifact), so this must share task_id.
    run2 = models.create_grading_run("job-ret-2", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    challenger_id = models.create_grading_result(run2, task_id, s1, "mueller.anna",
                                                  [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{challenger_id}/supersede',
                          data={"csrf_token": token, "winner": "challenger"}, follow_redirects=True)
    assert resp.status_code == 200
    assert models.get_grading_result(active_id)["status"] == "superseded"
    assert models.get_grading_result(active_id)["superseded_by_id"] == challenger_id
    assert models.get_grading_result(challenger_id)["status"] == "active"


def test_supersede_route_active_wins(app, client, as_admin, tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = ""
    klasse_id, task_id, run1 = _setup(job_id="job-ret-3")
    s1 = _student("Mueller", "Anna", "mueller.anna")
    active_id = models.create_grading_result(run1, task_id, s1, "mueller.anna",
                                              [{"name": "X", "score": 1, "max_score": 1}])
    models.release_grading_result(active_id, models.create_admin("prior2", "pw"))

    run2 = models.create_grading_run("job-ret-4", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    challenger_id = models.create_grading_result(run2, task_id, s1, "mueller.anna",
                                                  [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{challenger_id}/supersede',
                          data={"csrf_token": token, "winner": "active"}, follow_redirects=True)
    assert resp.status_code == 200
    assert models.get_grading_result(active_id)["status"] == "active"
    assert models.get_grading_result(challenger_id)["status"] == "discarded"


def test_supersede_route_no_conflict_redirects_with_warning(app, client, as_admin, tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path)
    klasse_id, task_id, run_id = _setup(job_id="job-ret-5")
    s1 = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, s1, "mueller.anna",
                                              [{"name": "X", "score": 1, "max_score": 1}])
    resp = as_admin.get(f'/admin/grading-result/{result_id}/supersede', follow_redirects=True)
    assert resp.status_code == 200
    assert "Kein Konflikt" in resp.get_data(as_text=True)


def test_purge_media_route(app, client, as_admin, tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path)
    config.GRADING_SERVICE_URL = ""
    klasse_id, task_id, run_id = _setup(job_id="job-ret-6")
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-run/{run_id}/purge-media',
                          data={"csrf_token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert models.get_grading_run(run_id)["media_purged_at"] is not None
