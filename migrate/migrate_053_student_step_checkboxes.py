"""Per-student opt-in: tick off the individual work steps inside an Aufgabe.

An Aufgabe runs 20 minutes on median (max 45) and holds 3 numbered steps on
median (max 10). Students lose their place inside those steps, so this lets
them tick each one off. Column only -- the ticks themselves are NOT stored
here.

Why the ticks live in the browser (localStorage), not in the database:
they are scratchpad state with a ~20 minute lifetime, obsolete the moment the
Aufgabe itself is ticked off in student_subtask. Keeping them client-side
means no write per click, and it keeps them private: a tick in the database
becomes data a teacher could look at, which changes what it means to the
student (assessment FOR learning, docs/research/formative_assessment_bpb.md).
The cost is that ticks do not follow a student from the school PC to home --
Patrick's call, taken 2026-08-31.

The setting itself belongs here, beside easy_reading_mode, because it must
survive a device change: a student who needs this needs it everywhere.

Default 0 -- off. The steps of an Aufgabe are already numbered and spaced
(5ba41cd); checkboxes are for students who lose their place, not for everyone.
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
    ('student', 'step_checkboxes',
     "ALTER TABLE student ADD COLUMN step_checkboxes INTEGER NOT NULL DEFAULT 0"),
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
        if 'student' not in existing_tables:
            print("Table 'student' does not exist, skipping.")
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
