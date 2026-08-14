"""Tests for sub-phase 2g/2h support functions: review-required release
guard, Page B queue ordering, override-rate calibration signal, non-submitter
detection.
"""
import models


def _setup(job_id="job-r1"):
    klasse_id = models.create_klasse("6a")
    task_id = models.create_task("unit-3-bilder-entdecken", "desc", "lz", "MBI", "6", "pflicht")
    admin_id = models.create_admin(f"admin_{job_id}", "pw")
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    return klasse_id, task_id, run_id, admin_id


def _student(nachname, vorname, netzwerk_id):
    return models.create_student(nachname, vorname, f"u{netzwerk_id}", "pw", netzwerk_id=netzwerk_id)


def test_release_blocked_by_unconfirmed_review_required(db):
    klasse_id, task_id, run_id, admin_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    criteria = [
        {"name": "Dateiname", "score": 2, "max_score": 2},
        {"name": "Folie Pixel-Bild", "score": 0, "max_score": 3, "review_required": True},
    ]
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", criteria)

    try:
        models.release_grading_result(result_id, admin_id)
        assert False, "expected ValueError for unconfirmed review_required criterion"
    except ValueError as e:
        assert "Folie Pixel-Bild" in str(e)


def test_release_succeeds_once_review_required_confirmed(db):
    klasse_id, task_id, run_id, admin_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    criteria = [
        {"name": "Folie Pixel-Bild", "score": 0, "max_score": 3, "review_required": True},
    ]
    result_id = models.create_grading_result(run_id, task_id, sid, "mueller.anna", criteria)

    models.save_grading_result_review(result_id, [
        {"name": "Folie Pixel-Bild", "llm_score": 0, "max_score": 3, "teacher_score": 0,
         "review_required": True, "confirmed": True},
    ])
    models.release_grading_result(result_id, admin_id)
    assert models.get_grading_result(result_id)["status"] == "active"


def test_non_submitter_detection(db):
    klasse_id, task_id, run_id, _ = _setup()
    sid = _student("Niemand", "Da", "niemand.da")
    result_id = models.create_grading_result(
        run_id, task_id, sid, "niemand.da", [], document_file=None, error="No document files found",
    )
    result = models.get_grading_result(result_id)
    assert models.is_non_submitter_result(result) is True


def test_review_queue_excludes_non_submitters_and_orders_flagged_first(db):
    klasse_id, task_id, run_id, _ = _setup()

    s_error = _student("Aachen", "Errorix", "aachen.errorix")
    s_zero = _student("Bauer", "Zeroine", "bauer.zeroine")
    s_clean = _student("Zimmer", "Cleanix", "zimmer.cleanix")
    s_nonsub = _student("Niemand", "Da", "niemand.da")

    r_error = models.create_grading_result(run_id, task_id, s_error, "aachen.errorix",
                                            [{"name": "X", "score": 1, "max_score": 1}],
                                            error="LLM parse failure", document_file="doc.pptx")
    r_zero = models.create_grading_result(run_id, task_id, s_zero, "bauer.zeroine",
                                           [{"name": "Bild", "score": 0, "max_score": 3}])
    r_clean = models.create_grading_result(run_id, task_id, s_clean, "zimmer.cleanix",
                                            [{"name": "X", "score": 1, "max_score": 1}])
    models.create_grading_result(run_id, task_id, s_nonsub, "niemand.da", [],
                                  document_file=None, error="No document files found")

    queue = models.get_grading_run_review_queue(run_id)
    queue_ids = [r["id"] for r in queue]
    assert queue_ids == [r_error, r_zero, r_clean]


def test_get_next_in_review_queue(db):
    klasse_id, task_id, run_id, _ = _setup()
    s1 = _student("Aachen", "A", "aachen.a")
    s2 = _student("Bauer", "B", "bauer.b")
    r1 = models.create_grading_result(run_id, task_id, s1, "aachen.a", [{"name": "X", "score": 1, "max_score": 1}])
    r2 = models.create_grading_result(run_id, task_id, s2, "bauer.b", [{"name": "X", "score": 1, "max_score": 1}])

    assert models.get_next_in_review_queue(run_id, r1)["id"] == r2
    assert models.get_next_in_review_queue(run_id, r2) is None


def test_override_rate_none_when_unreviewed(db):
    klasse_id, task_id, run_id, _ = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    models.create_grading_result(run_id, task_id, sid, "mueller.anna",
                                  [{"name": "X", "score": 1, "max_score": 1}])
    assert models.get_grading_run_override_rate(run_id) is None


def test_override_rate_computed_after_review(db):
    klasse_id, task_id, run_id, _ = _setup()
    s1 = _student("A", "A", "a.a")
    s2 = _student("B", "B", "b.b")
    r1 = models.create_grading_result(run_id, task_id, s1, "a.a", [{"name": "X", "score": 1, "max_score": 2}])
    r2 = models.create_grading_result(run_id, task_id, s2, "b.b", [{"name": "X", "score": 1, "max_score": 2}])

    models.save_grading_result_review(r1, [{"name": "X", "llm_score": 1, "max_score": 2, "teacher_score": 2}])  # overridden
    models.save_grading_result_review(r2, [{"name": "X", "llm_score": 1, "max_score": 2, "teacher_score": 1}])  # not overridden

    assert models.get_grading_run_override_rate(run_id) == 0.5
