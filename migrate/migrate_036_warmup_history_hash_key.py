"""Rekey warmup_history by question content hash instead of position.

Fixes fragility: warmup_history previously keyed by
(student_id, task_id, subtask_id, question_index). If a teacher inserts,
removes, or reorders a question inside a quiz, question_index shifts and
previously-recorded history silently attaches to the wrong question (wrong
difficulty classification for a few sessions). Rekeys onto question_hash,
the same content hash (_question_hash() in models.py) the app now uses to
read/write this table - reused here so the migration and the runtime code
can never disagree on what a given question hashes to.

Rows whose (task_id/subtask_id, question_index) no longer resolves to a real
question in the current quiz_json (deleted/out-of-range) are dropped - that
history was already unreliable and can't be re-anchored to real content.

Ref: todo.md "Fix warmup_history index fragility".
"""
import json
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE
import models


def _resolve_question_def(conn, task_id, subtask_id, question_index):
    """Question dict currently at this position, or None if it no longer exists."""
    if subtask_id is not None:
        row = conn.execute("SELECT quiz_json FROM subtask WHERE id = ?", (subtask_id,)).fetchone()
    else:
        row = conn.execute("SELECT quiz_json FROM task WHERE id = ?", (task_id,)).fetchone()
    if not row or not row[0]:
        return None
    try:
        questions = json.loads(row[0]).get('questions', [])
    except (json.JSONDecodeError, TypeError):
        return None
    if question_index is None or not (0 <= question_index < len(questions)):
        return None
    return questions[question_index]


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(warmup_history)").fetchall()]
        if 'question_hash' in columns:
            print("warmup_history already keyed by question_hash, skipping.")
            return

        rows = conn.execute(
            "SELECT student_id, task_id, subtask_id, question_index, "
            "times_shown, times_correct, last_shown, streak FROM warmup_history"
        ).fetchall()
        print(f"Found {len(rows)} existing warmup_history rows.")

        conn.execute("""
            CREATE TABLE warmup_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                task_id INTEGER,
                subtask_id INTEGER,
                question_hash TEXT NOT NULL,
                times_shown INTEGER NOT NULL DEFAULT 0,
                times_correct INTEGER NOT NULL DEFAULT 0,
                last_shown DATE,
                streak INTEGER NOT NULL DEFAULT 0,
                UNIQUE(student_id, task_id, subtask_id, question_hash),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            )
        """)

        kept, merged, dropped = 0, 0, 0
        for row in rows:
            q_def = _resolve_question_def(conn, row['task_id'], row['subtask_id'], row['question_index'])
            if q_def is None:
                dropped += 1
                continue
            q_hash = models._question_hash(q_def)

            existing = conn.execute(
                "SELECT id, last_shown FROM warmup_history_new "
                "WHERE student_id = ? AND task_id IS ? AND subtask_id IS ? AND question_hash = ?",
                (row['student_id'], row['task_id'], row['subtask_id'], q_hash)
            ).fetchone()
            if existing:
                # Two old index-keyed rows now collapse onto the same content
                # hash (e.g. a duplicate question). Sum the counters, keep the
                # later last_shown.
                merged += 1
                last_shown = max(filter(None, [existing['last_shown'], row['last_shown']]), default=None)
                conn.execute(
                    "UPDATE warmup_history_new SET times_shown = times_shown + ?, "
                    "times_correct = times_correct + ?, last_shown = ? WHERE id = ?",
                    (row['times_shown'], row['times_correct'], last_shown, existing['id'])
                )
            else:
                kept += 1
                conn.execute(
                    "INSERT INTO warmup_history_new "
                    "(student_id, task_id, subtask_id, question_hash, times_shown, times_correct, last_shown, streak) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (row['student_id'], row['task_id'], row['subtask_id'], q_hash,
                     row['times_shown'], row['times_correct'], row['last_shown'], row['streak'])
                )

        conn.execute("DROP TABLE warmup_history")
        conn.execute("ALTER TABLE warmup_history_new RENAME TO warmup_history")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warmup_student ON warmup_history(student_id, last_shown)")
        conn.commit()
        print(f"Rekeyed: {kept} carried over, {merged} merged onto an existing hash, "
              f"{dropped} dropped (question no longer resolvable).")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
