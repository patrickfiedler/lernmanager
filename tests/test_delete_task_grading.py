"""Deleting a topic must also clear its grading rows.

grading_run/grading_result FK task(id) without ON DELETE CASCADE (migrations
040/041), and delete_task() did not clear them -- so any topic that had ever
been through the LLM grading pipeline could not be deleted. Reproduced from
production: "5 - Bots, Bytes und Botschaften" (graded_artifact 'mein-blog').
"""
import re
import models


def _csrf_token(client):
    resp = client.get('/admin')
    return re.search(r'name="csrf-token" content="([^"]+)"',
                     resp.get_data(as_text=True)).group(1)


def _task_with_grading(released=False):
    task_id = models.create_task("5 - Bots", "", "", "MBI", "5", "pflicht")
    run_id = models.create_grading_run(
        "job-1", None, task_id, "mein-blog", "ollama", "qwen3", total_students=1)
    result_id = models.create_grading_result(
        run_id, task_id, None, "muster.max", [{"name": "K1", "score": 2, "max_score": 3}])
    if released:
        with models.db_session() as conn:
            conn.execute("UPDATE grading_result SET released_at = ? WHERE id = ?",
                         ("2026-08-25T10:00:00", result_id))
    return task_id


def test_delete_task_with_grading_run_succeeds(db):
    task_id = _task_with_grading()

    models.delete_task(task_id)

    assert models.get_task(task_id) is None
    with models.db_session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM grading_run WHERE task_id = ?",
                            (task_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM grading_result WHERE task_id = ?",
                            (task_id,)).fetchone()[0] == 0


def test_deletion_impact_reports_released_grades(db):
    task_id = _task_with_grading(released=True)

    impact = models.get_task_deletion_impact(task_id)

    assert impact["grading_runs"] == 1
    assert impact["grading_results"] == 1
    assert impact["released_grades"] == 1


def test_delete_route_reports_what_it_removed(as_admin, db):
    task_id = _task_with_grading()

    resp = as_admin.post(f"/admin/thema/{task_id}/loeschen",
                         data={"csrf_token": _csrf_token(as_admin)},
                         follow_redirects=True)
    html = resp.get_data(as_text=True)

    assert "Thema gelöscht." in html
    assert "1 Bewertung(en)" in html
    assert models.get_task(task_id) is None


def test_no_remaining_non_cascading_fk_into_task(db):
    """Guard: a new table FK-ing task/subtask without CASCADE must be added to
    delete_task(), or topic deletion silently breaks again."""
    known = {
        ("artifact_feedback", "subtask"), ("artifact_gate_attempt", "subtask"),
        ("student_artifact_file", "task"), ("student_artifact_file", "subtask"),
        ("grading_run", "task"), ("grading_result", "task"),
    }
    with models.db_session() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        found = set()
        for table in tables:
            for fk in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
                if fk["table"] in ("task", "subtask") and fk["on_delete"] != "CASCADE":
                    found.add((table, fk["table"]))

    assert found == known, f"unhandled non-cascading FK into task/subtask: {found - known}"
