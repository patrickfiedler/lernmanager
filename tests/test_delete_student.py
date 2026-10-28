"""Deleting a student must clear every row that FKs student(id) without cascade.

artifact_gate_attempt (migrate_026) and grading_result (migrate_040) were missed
by delete_student(), so any student who had ever hit an artifact gate or been
through LLM grading could not be deleted: "FOREIGN KEY constraint failed".
Reproduced from production, /admin/schueler/152/loeschen.
"""
import inspect
import models


def _student_with_grading_history():
    task_id = models.create_task("5 - Bots", "", "", "MBI", "5", "pflicht")
    models.update_subtasks(task_id, ["### Blog"])
    subtask_id = models.get_subtasks(task_id)[0]['id']
    student_id = models.create_student("Muster", "Max", "happypanda", "bacado42")
    models.log_artifact_gate_attempt(student_id, subtask_id, False, [])
    run_id = models.create_grading_run(
        "job-1", None, task_id, "mein-blog", "ollama", "qwen3", total_students=1)
    models.create_grading_result(
        run_id, task_id, student_id, "muster.max", [{"name": "K1", "score": 2, "max_score": 3}])
    return student_id


def test_delete_student_with_gate_attempt_and_grading_result(db):
    student_id = _student_with_grading_history()

    models.delete_student(student_id)

    assert models.get_student(student_id) is None


def test_every_non_cascading_student_fk_is_cleared(db):
    """Guard for the next table: a new FK to student(id) needs ON DELETE CASCADE
    or an explicit DELETE in _delete_student_rows()."""
    source = inspect.getsource(models._delete_student_rows)
    with models.db_session() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        missed = [t for t in tables
                  for fk in conn.execute(f"PRAGMA foreign_key_list('{t}')")
                  if fk['table'] == 'student' and fk['on_delete'] != 'CASCADE'
                  and f"DELETE FROM {t} " not in source]
    assert missed == []


def test_class_delete_is_all_or_nothing(db):
    """If one student cannot be deleted, nobody in the class is -- a half-done
    loop lost the upload filenames of the students already gone."""
    import sqlite3
    import pytest
    klasse_id = models.create_klasse("7a")
    first = models.create_student("A", "Anna", "u1", "pw")
    second = models.create_student("B", "Ben", "u2", "pw")
    for sid in (first, second):
        models.add_student_to_klasse(sid, klasse_id)
    with models.db_session() as conn:
        conn.execute("CREATE TABLE blocker (student_id INTEGER REFERENCES student(id))")
        conn.execute("INSERT INTO blocker VALUES (?)", (second,))

    with pytest.raises(sqlite3.IntegrityError):
        models.delete_all_students_in_klasse(klasse_id)

    assert models.get_student(first) is not None
