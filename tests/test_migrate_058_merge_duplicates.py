"""The duplicate-merge migration must not cost a student a tick or an attempt.

Repointing children rather than deleting the newer row is the whole point: in
production 17 of the 30 shadowed rows already carried a redone Aufgabe and its
quiz attempts, and a quiz attempt is a graded record.
"""
import importlib
import os
import sys

import config
import models

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrate'))


def _migration():
    mod = importlib.import_module('migrate_058_merge_duplicate_student_tasks')
    mod.DATABASE = config.DATABASE  # captured at import time
    return mod


def _duplicate_rows(student_id, klasse_id, task_id):
    with models.db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM student_task WHERE student_id = ? AND klasse_id = ? AND task_id = ?",
            (student_id, klasse_id, task_id)).fetchall()]


def _make_duplicate(db_unused=None):
    """Recreate the production shape: a finished row holding the real work, and
    an empty active row inserted on top of it by the old dead guard."""
    klasse_id = models.create_klasse("6a")
    student_id = models.create_student("Mueller", "Anna", "u1", "pw")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Thema A", "d", "l", "MBI", "6", "pflicht")
    sub_a = models.create_subtask(task_id, "Aufgabe 1", reihenfolge=1)
    sub_b = models.create_subtask(task_id, "Aufgabe 2", reihenfolge=2)

    models.assign_task_to_student(student_id, klasse_id, task_id)
    old = models.get_student_task(student_id, klasse_id)['id']
    models.toggle_student_subtask(old, sub_a, True)
    models.toggle_student_subtask(old, sub_b, True)
    models.save_quiz_attempt(old, 5, 5, "{}")
    models.mark_task_complete(old, manual=True)

    with models.db_session() as conn:
        cur = conn.execute(
            "INSERT INTO student_task (student_id, klasse_id, task_id, rolle, abgeschlossen, "
            "manuell_abgeschlossen) VALUES (?, ?, ?, 'primary', 0, 0)",
            (student_id, klasse_id, task_id))
        new = cur.lastrowid
    # The student redid Aufgabe 1 on the new row before anyone noticed.
    models.toggle_student_subtask(new, sub_a, True)
    models.save_quiz_attempt(new, 3, 5, "{}")
    return klasse_id, student_id, task_id, old, new, sub_a, sub_b


def test_merge_keeps_every_tick_and_attempt(db):
    klasse_id, student_id, task_id, old, new, sub_a, sub_b = _make_duplicate()
    with models.db_session() as conn:
        attempts_before = conn.execute("SELECT COUNT(*) c FROM quiz_attempt").fetchone()['c']

    _migration().run()

    rows = _duplicate_rows(student_id, klasse_id, task_id)
    assert len(rows) == 1
    kept = rows[0]
    assert kept['id'] == old, "the row carrying the work wins"
    assert kept['abgeschlossen'] == 1, "the student really did finish this topic"

    ticked = {p['id'] for p in models.get_student_subtask_progress(kept['id']) if p['erledigt']}
    assert ticked == {sub_a, sub_b}
    with models.db_session() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM quiz_attempt").fetchone()['c'] == attempts_before
        orphans = conn.execute(
            "SELECT COUNT(*) c FROM quiz_attempt qa WHERE NOT EXISTS "
            "(SELECT 1 FROM student_task st WHERE st.id = qa.student_task_id)").fetchone()['c']
    assert orphans == 0


def test_merge_is_idempotent(db):
    klasse_id, student_id, task_id, *_ = _make_duplicate()
    mod = _migration()
    mod.run()
    mod.run()
    assert len(_duplicate_rows(student_id, klasse_id, task_id)) == 1


def test_merge_leaves_a_clean_database_alone(db):
    klasse_id = models.create_klasse("6a")
    student_id = models.create_student("Mueller", "Anna", "u1", "pw")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Thema A", "d", "l", "MBI", "6", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, task_id)

    _migration().run()

    assert len(_duplicate_rows(student_id, klasse_id, task_id)) == 1
    assert models.get_student_task(student_id, klasse_id)['abgeschlossen'] == 0
