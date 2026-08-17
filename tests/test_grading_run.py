"""Tests for grading_run/grading_result (migrate_040) -- the teacher-review
state machine from grading-service-deployment.md §7:
imported -> under_review -> active, with corrected/discarded/superseded
side states, and "at most one active row per (student, artifact)".
"""
import models


def _setup(klasse_name="6a", task_name="unit-3-bilder-entdecken"):
    klasse_id = models.create_klasse(klasse_name)
    task_id = models.create_task(task_name, "desc", "lz", "MBI", "6", "pflicht")
    student_id = models.create_student("Mueller", "Anna", f"u{klasse_name}{task_name}", "pw", netzwerk_id="mueller.anna")
    admin_id = models.create_admin(f"admin_{klasse_name}_{task_name}", "pw")
    return klasse_id, task_id, student_id, admin_id


_CRITERIA = [
    {"name": "Dateiname", "score": 2, "max_score": 2, "feedback": "ok"},
    {"name": "Bild", "score": 0, "max_score": 3, "feedback": "kein Bild"},
]


def test_create_run_and_result_starts_imported(db):
    klasse_id, task_id, student_id, _ = _setup()
    run_id = models.create_grading_run("job-1", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    result_id = models.create_grading_result(run_id, task_id, student_id, "mueller.anna", _CRITERIA,
                                              llm_total_score=2, llm_max_score=5, flagged=True)
    result = models.get_grading_result(result_id)
    assert result["status"] == "imported"
    assert result["flagged"] is True
    assert result["llm_total_score"] == 2
    assert len(result["criteria"]) == 2
    assert result["criteria"][1]["teacher_score"] == 0  # prefilled = llm_score


def test_list_grading_results_includes_student_name(db):
    klasse_id, task_id, student_id, _ = _setup()
    run_id = models.create_grading_run("job-2", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    models.create_grading_result(run_id, task_id, student_id, "mueller.anna", _CRITERIA)
    results = models.list_grading_results(run_id)
    assert len(results) == 1
    assert results[0]["nachname"] == "Mueller"


def test_save_review_marks_overridden_and_under_review(db):
    klasse_id, task_id, student_id, _ = _setup()
    run_id = models.create_grading_run("job-3", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    result_id = models.create_grading_result(run_id, task_id, student_id, "mueller.anna", _CRITERIA,
                                              llm_total_score=2, llm_max_score=5)

    models.save_grading_result_review(result_id, [
        {"name": "Dateiname", "llm_score": 2, "max_score": 2, "teacher_score": 2},
        {"name": "Bild", "llm_score": 0, "max_score": 3, "teacher_score": 3},
    ])

    result = models.get_grading_result(result_id)
    assert result["status"] == "under_review"
    assert result["teacher_total_score"] == 5
    assert result["criteria"][0]["overridden"] is False
    assert result["criteria"][1]["overridden"] is True


def test_release_sets_active_and_visible_via_get_active(db):
    klasse_id, task_id, student_id, admin_id = _setup()
    run_id = models.create_grading_run("job-4", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    result_id = models.create_grading_result(run_id, task_id, student_id, "mueller.anna", _CRITERIA)

    models.release_grading_result(result_id, admin_id)

    result = models.get_grading_result(result_id)
    assert result["status"] == "active"
    assert result["released_by"] == admin_id
    active = models.get_active_grading_result(student_id, task_id)
    assert active["id"] == result_id


def test_release_conflict_raises_without_mutating(db):
    klasse_id, task_id, student_id, admin_id = _setup()
    run1 = models.create_grading_run("job-5a", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r1 = models.create_grading_result(run1, task_id, student_id, "mueller.anna", _CRITERIA)
    models.release_grading_result(r1, admin_id)

    run2 = models.create_grading_run("job-5b", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r2 = models.create_grading_result(run2, task_id, student_id, "mueller.anna", _CRITERIA)

    try:
        models.release_grading_result(r2, admin_id)
        assert False, "expected ValueError on unresolved supersede conflict"
    except ValueError:
        pass

    assert models.get_grading_result(r2)["status"] == "imported"
    assert models.get_grading_result(r1)["status"] == "active"


def test_supersede_then_release_switches_active_pointer(db):
    klasse_id, task_id, student_id, admin_id = _setup()
    run1 = models.create_grading_run("job-6a", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r1 = models.create_grading_result(run1, task_id, student_id, "mueller.anna", _CRITERIA)
    models.release_grading_result(r1, admin_id)

    run2 = models.create_grading_run("job-6b", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r2 = models.create_grading_result(run2, task_id, student_id, "mueller.anna", _CRITERIA)

    models.supersede_grading_result(r1, r2)
    models.release_grading_result(r2, admin_id)

    assert models.get_grading_result(r1)["status"] == "superseded"
    assert models.get_grading_result(r1)["superseded_by_id"] == r2
    assert models.get_grading_result(r2)["status"] == "active"
    assert models.get_active_grading_result(student_id, task_id)["id"] == r2


def test_discard_result_and_run(db):
    klasse_id, task_id, student_id, admin_id = _setup()
    run_id = models.create_grading_run("job-7", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r1 = models.create_grading_result(run_id, task_id, student_id, "mueller.anna", _CRITERIA)

    models.discard_grading_result(r1)
    assert models.get_grading_result(r1)["status"] == "discarded"

    student2 = models.create_student("Schmidt", "Jan", "schmidtjan_discard", "pw", netzwerk_id="schmidt.jan")
    r2 = models.create_grading_result(run_id, task_id, student2, "schmidt.jan", _CRITERIA)
    models.release_grading_result(r2, admin_id)

    models.discard_grading_run(run_id)
    # Active results survive a bulk run-discard; only non-active ones get swept.
    assert models.get_grading_result(r2)["status"] == "active"


def test_mark_run_media_purged(db):
    klasse_id, task_id, _, _ = _setup()
    run_id = models.create_grading_run("job-8", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    assert models.get_grading_run(run_id)["media_purged_at"] is None
    models.mark_grading_run_media_purged(run_id)
    assert models.get_grading_run(run_id)["media_purged_at"] is not None


def test_unresolved_student_id_none_never_active(db):
    klasse_id, task_id, _, admin_id = _setup()
    run_id = models.create_grading_run("job-9", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    r1 = models.create_grading_result(run_id, task_id, None, "unmatched.folder", _CRITERIA)

    try:
        models.release_grading_result(r1, admin_id)
        assert False, "expected ValueError for unmatched student_id"
    except ValueError:
        pass


# --- klasse_id nullable (migrate_041, multi-class upload redesign) --------

def test_create_grading_run_without_klasse(db):
    task_id = models.create_task("unit-3-bilder-entdecken", "desc", "lz", "MBI", "6", "pflicht")
    run_id = models.create_grading_run("job-10", None, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    run = models.get_grading_run(run_id)
    assert run["klasse_id"] is None
    assert run["klasse_name"] is None
    assert run["task_id"] == task_id


def test_list_grading_runs_includes_classless_runs(db):
    klasse_id, task_id, _, _ = _setup()
    models.create_grading_run("job-11a", klasse_id, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    models.create_grading_run("job-11b", None, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")

    job_ids = {r["job_id"] for r in models.list_grading_runs()}
    assert {"job-11a", "job-11b"} <= job_ids


def test_grading_run_job_id_is_unique(db):
    task_id = models.create_task("unit-3-bilder-entdecken", "desc", "lz", "MBI", "6", "pflicht")
    models.create_grading_run("job-dup", None, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
    import sqlite3
    try:
        models.create_grading_run("job-dup", None, task_id, "unit-3-bilder-entdecken", "ollama", "qwen3.6")
        assert False, "expected IntegrityError for duplicate job_id"
    except sqlite3.IntegrityError:
        pass
