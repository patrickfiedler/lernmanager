"""Route-level tests for Page A (grading_run_detail) and Page B
(grading_review) -- sub-phases 2g/2h.
"""
import re

import models


def _csrf_token(client):
    resp = client.get('/admin')
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1)


def _setup(job_id="job-page"):
    klasse_id = models.create_klasse("6a")
    task_id = models.create_task("unit-3-bilder-entdecken", "desc", "lz", "MBI", "6", "pflicht")
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    return klasse_id, task_id, run_id


def _student(nachname, vorname, netzwerk_id):
    return models.create_student(nachname, vorname, f"u{netzwerk_id}", "pw", netzwerk_id=netzwerk_id)


def test_page_a_requires_admin(app, client):
    _, _, run_id = _setup()
    resp = client.get(f'/admin/grading-run/{run_id}')
    assert resp.status_code in (302, 401, 403)


def test_page_a_shows_roster_and_non_submitters(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Mueller", "Anna", "mueller.anna")
    s2 = _student("Niemand", "Da", "niemand.da")
    models.create_grading_result(run_id, task_id, s1, "mueller.anna",
                                  [{"name": "X", "score": 1, "max_score": 1}])
    models.create_grading_result(run_id, task_id, s2, "niemand.da", [],
                                  document_file=None, error="No document files found")

    resp = as_admin.get(f'/admin/grading-run/{run_id}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Mueller, Anna" in body
    assert "Niemand, Da" in body


def test_page_a_bulk_release_partitions_conflicts(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Mueller", "Anna", "mueller.anna")
    r1 = models.create_grading_result(run_id, task_id, s1, "mueller.anna",
                                       [{"name": "X", "score": 1, "max_score": 1}])
    models.release_grading_result(r1, models.create_admin("prior_admin", "pw"))

    # A second run producing a competing result for the same student+task.
    run_id2 = models.create_grading_run("job-page-2", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r2 = models.create_grading_result(run_id2, task_id, s1, "mueller.anna",
                                       [{"name": "X", "score": 1, "max_score": 1}])

    resp = as_admin.get(f'/admin/grading-run/{run_id2}')
    body = resp.get_data(as_text=True)
    assert "einzeln über" in body  # conflict-needs-decision messaging


def test_page_a_release_bulk_action(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, s1, "mueller.anna",
                                              [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-run/{run_id}/release-bulk',
                          data={"csrf_token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert models.get_grading_result(result_id)["status"] == "active"


def test_page_a_confirm_non_submitter(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Niemand", "Da", "niemand.da")
    result_id = models.create_grading_result(run_id, task_id, s1, "niemand.da", [],
                                              document_file=None, error="No document files found")
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{result_id}/confirm',
                          data={"csrf_token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert models.get_grading_result(result_id)["status"] == "active"


def test_page_a_discard_run(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, s1, "mueller.anna",
                                              [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-run/{run_id}/discard',
                          data={"csrf_token": token}, follow_redirects=True)
    assert resp.status_code == 200
    assert models.get_grading_result(result_id)["status"] == "discarded"


def test_page_b_renders_criteria_and_position(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, s1, "mueller.anna", [
        {"name": "Dateiname", "score": 2, "max_score": 2},
        {"name": "Folie Pixel-Bild", "score": 0, "max_score": 3, "review_required": True},
    ])

    resp = as_admin.get(f'/admin/grading-result/{result_id}/review')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Dateiname" in body
    assert "Folie Pixel-Bild" in body
    assert "Prüfung nötig" in body
    assert "1 / 1" in body


def test_page_b_save_persists_teacher_score(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Mueller", "Anna", "mueller.anna")
    result_id = models.create_grading_result(run_id, task_id, s1, "mueller.anna", [
        {"name": "Dateiname", "score": 2, "max_score": 2},
    ])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{result_id}/review', data={
        "csrf_token": token, "action": "save", "teacher_score_0": "1",
    }, follow_redirects=True)
    assert resp.status_code == 200

    result = models.get_grading_result(result_id)
    assert result["status"] == "under_review"
    assert result["criteria"][0]["teacher_score"] == 1
    assert result["criteria"][0]["overridden"] is True


def test_page_b_save_next_advances_to_next_in_queue(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Aachen", "A", "aachen.a")
    s2 = _student("Bauer", "B", "bauer.b")
    r1 = models.create_grading_result(run_id, task_id, s1, "aachen.a",
                                       [{"name": "X", "score": 1, "max_score": 1}])
    r2 = models.create_grading_result(run_id, task_id, s2, "bauer.b",
                                       [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{r1}/review', data={
        "csrf_token": token, "action": "save_next", "teacher_score_0": "1",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/admin/grading-result/{r2}/review")


def test_page_b_save_next_at_end_returns_to_page_a(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Aachen", "A", "aachen.a")
    r1 = models.create_grading_result(run_id, task_id, s1, "aachen.a",
                                       [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{r1}/review', data={
        "csrf_token": token, "action": "save_next", "teacher_score_0": "1",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/admin/grading-run/{run_id}")


def test_page_b_skip_does_not_write(app, client, as_admin):
    klasse_id, task_id, run_id = _setup()
    s1 = _student("Aachen", "A", "aachen.a")
    s2 = _student("Bauer", "B", "bauer.b")
    r1 = models.create_grading_result(run_id, task_id, s1, "aachen.a",
                                       [{"name": "X", "score": 1, "max_score": 1}])
    models.create_grading_result(run_id, task_id, s2, "bauer.b",
                                  [{"name": "X", "score": 1, "max_score": 1}])
    token = _csrf_token(as_admin)

    resp = as_admin.post(f'/admin/grading-result/{r1}/review', data={
        "csrf_token": token, "action": "skip", "teacher_score_0": "0",
    })
    assert resp.status_code == 302
    result = models.get_grading_result(r1)
    assert result["status"] == "imported"  # unchanged -- skip never writes
    assert result["criteria"][0]["teacher_score"] == 1  # still the prefilled llm_score


def test_download_grading_media_blocks_path_traversal(app, client, as_admin, tmp_path):
    import config
    config.UPLOAD_FOLDER = str(tmp_path)
    resp = as_admin.get('/grading-medien/../../../../etc/passwd')
    assert resp.status_code == 404
