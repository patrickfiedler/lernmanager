"""Demo flag for practice mode.

Patrick, 2026-10-26: a demo account has to show Üben without first sitting every
quiz and waiting for the checkpoint review. The teacher sets the flag on
admin/schueler_detail; models.get_warmup_question_pool then admits every question
of every assigned Thema, checkpoints included.

    student.demo_practice   1 = practice pool ignores attempts and checkpoint gates
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

# Written out in full: tests/test_schema_parity.py greps for the literal
# "ALTER TABLE <t> ADD COLUMN <c>" text.
NEW_COLUMNS = [
    ('student', 'demo_practice',
     "ALTER TABLE student ADD COLUMN demo_practice INTEGER NOT NULL DEFAULT 0"),
]


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
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
