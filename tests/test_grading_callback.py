"""Tests for /internal/grading/results (sub-phase 2e) and
models.import_grading_callback -- the machine-to-machine endpoint the
grading service's worker.fire_callback() posts to.
"""
import json

import config
import models


def _setup_run(klasse_name="6a", task_name="unit-3-bilder-entdecken", job_id="job-cb-1"):
    klasse_id = models.create_klasse(klasse_name)
    task_id = models.create_task(task_name, "desc", "lz", "MBI", "6", "pflicht")
    models.create_student("Mueller", "Anna", f"u{job_id}", "pw", netzwerk_id="mueller.anna")
    # This grading_run row is what sub-phase 2f's upload flow creates before
    # the job runs -- the callback importer looks it up by job_id.
    run_id = models.create_grading_run(job_id, klasse_id, task_id, task_name, "ollama", None)
    return klasse_id, task_id, run_id


_STUDENTS_PAYLOAD = [
    {
        "student_id": "mueller.anna",
        "total_score": 2, "max_score": 5, "flagged": True, "confidence": "medium",
        "error": None, "document_file": "steckbrief.pptx",
        "criteria": [
            {"name": "Dateiname", "score": 2, "max_score": 2, "feedback": "ok", "review_required": False},
            {"name": "Folie Pixel-Bild", "score": 0, "max_score": 3, "feedback": "kein Bild", "review_required": True},
        ],
        "media": [{"file": "media/mueller.anna/001.jpg", "kind": "image"}],
        "media_skipped": [],
    },
]


def test_import_grading_callback_creates_results(db):
    klasse_id, task_id, run_id = _setup_run()

    imported_run_id = models.import_grading_callback(
        job_id="job-cb-1", provider="ollama", model="qwen3.6",
        graded_at="2026-08-14T12:00:00Z", students=_STUDENTS_PAYLOAD,
    )

    assert imported_run_id == run_id
    run = models.get_grading_run(run_id)
    assert run["provider"] == "ollama"
    assert run["model"] == "qwen3.6"
    assert run["total_students"] == 1
    assert run["flagged_count"] == 1

    results = models.list_grading_results(run_id)
    assert len(results) == 1
    r = results[0]
    assert r["nachname"] == "Mueller"
    assert r["status"] == "imported"
    assert r["criteria"][1]["review_required"] is True
    assert r["media"] == [{"file": "media/mueller.anna/001.jpg", "kind": "image"}]


def test_import_grading_callback_unmatched_student_gets_null_student_id(db):
    klasse_id, task_id, run_id = _setup_run(job_id="job-cb-2")
    payload = [dict(_STUDENTS_PAYLOAD[0], student_id="unknown.folder")]

    models.import_grading_callback(
        job_id="job-cb-2", provider="ollama", model="qwen3.6",
        graded_at="2026-08-14T12:00:00Z", students=payload,
    )

    results = models.list_grading_results(run_id)
    assert results[0]["student_id"] is None
    assert results[0]["nachname"] is None


def test_import_grading_callback_unknown_job_id_raises(db):
    try:
        models.import_grading_callback(
            job_id="does-not-exist", provider="ollama", model=None,
            graded_at=None, students=[],
        )
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_import_grading_callback_is_idempotent_per_student(db):
    _setup_run(job_id="job-cb-3")
    models.import_grading_callback(
        job_id="job-cb-3", provider="ollama", model="qwen3.6",
        graded_at="t", students=_STUDENTS_PAYLOAD,
    )
    # Re-delivery of the same callback (fire-and-forget retry) must not duplicate.
    models.import_grading_callback(
        job_id="job-cb-3", provider="ollama", model="qwen3.6",
        graded_at="t", students=_STUDENTS_PAYLOAD,
    )
    run = models.get_grading_run_by_job_id("job-cb-3")
    results = models.list_grading_results(run["id"])
    assert len(results) == 1


def test_route_rejects_missing_secret(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post('/internal/grading/results', json={"job_id": "x"})
    assert resp.status_code == 401


def test_route_rejects_wrong_secret(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post(
        '/internal/grading/results', json={"job_id": "x"},
        headers={"X-Grading-Callback-Secret": "wrong"},
    )
    assert resp.status_code == 401


def test_route_accepts_correct_secret_and_imports(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    klasse_id, task_id, run_id = _setup_run(job_id="job-cb-route")

    resp = client.post(
        '/internal/grading/results',
        data=json.dumps({
            "job_id": "job-cb-route", "provider": "ollama", "model": "qwen3.6",
            "graded_at": "2026-08-14T12:00:00Z", "students": _STUDENTS_PAYLOAD,
        }),
        content_type='application/json',
        headers={"X-Grading-Callback-Secret": "s3cr3t"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["grading_run_id"] == run_id
    assert len(models.list_grading_results(run_id)) == 1


def test_route_unknown_job_id_returns_404(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post(
        '/internal/grading/results',
        data=json.dumps({"job_id": "no-such-job", "students": []}),
        content_type='application/json',
        headers={"X-Grading-Callback-Secret": "s3cr3t"},
    )
    assert resp.status_code == 404
