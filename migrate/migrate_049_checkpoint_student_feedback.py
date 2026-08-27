"""Student-visible teacher feedback on a Chemie Quiz-checkpoint.

Students see the LLM's score the moment they finish; the teacher reviews later.
Until now that review was entirely invisible to them -- they had no way to tell
whether anyone had looked, or whether the mark they saw still stood.

This adds ONE column, checkpoint_attempt.student_feedback, and deliberately does
not reuse the existing teacher_note. teacher_note is documented in init_db() as
"shown to nobody but the teacher", and rows have already been written under that
promise; making it student-visible retroactively would publish candid notes their
author never intended anyone else to read. A new field starts empty and carries
no such history.

Everything else the student needs is already derivable and needs no storage:
  reviewed at all  -> reviewed_at IS NOT NULL   (the fact, never the timestamp --
                      Patrick's call: students see THAT it was checked, not when)
  accepted/changed -> effective_checkpoint_score(attempt) != score
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

# Written out in full rather than assembled from table/column names:
# tests/test_schema_parity.py greps migrate/*.py for the literal
# "ALTER TABLE <t> ADD COLUMN <c>" text, and a built string is invisible to it.
NEW_COLUMNS = [
    ('checkpoint_attempt', 'student_feedback',
     "ALTER TABLE checkpoint_attempt ADD COLUMN student_feedback TEXT"),
]


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        existing_tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if 'checkpoint_attempt' not in existing_tables:
            print("Table 'checkpoint_attempt' does not exist, skipping (run migrate_047 first).")
            return

        added = 0
        for table, column, statement in NEW_COLUMNS:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column in cols:
                print(f"  {table}.{column} already exists, skipping.")
                continue
            conn.execute(statement)
            print(f"  Added {table}.{column}.")
            added += 1

        conn.commit()
        print(f"\nDone. {added} column(s) added.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
