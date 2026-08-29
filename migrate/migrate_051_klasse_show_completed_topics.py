"""Per-class opt-in: list a student's finished Themen on their dashboard.

The dashboard shows only the *current* topic per class (get_student_task), so a
student who has advanced through the topic queue has no link back to anything
they finished. The topic stays reachable by slug URL, but nothing points there.
That became a real problem once checkpoints could be reopened: the teacher
reopens a checkpoint on a Thema the student left weeks ago, and the student is
never shown a way back to it.

One column, klasse.show_completed_topics, default 0 -- off, opt-in per class
(Patrick's call). A class working a long queue wants the back-links; a class
sitting on a single Thema would just get clutter.

Deliberately NOT gated by this flag: the reopened-checkpoint notice. That one is
actionable rather than archival, so it shows for every class. The flag governs
the archive only.
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
    ('klasse', 'show_completed_topics',
     "ALTER TABLE klasse ADD COLUMN show_completed_topics INTEGER NOT NULL DEFAULT 0"),
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
        if 'klasse' not in existing_tables:
            print("Table 'klasse' does not exist, skipping.")
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
