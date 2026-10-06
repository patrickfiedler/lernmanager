"""Keep the question wording with every checkpoint answer.

Review 2026-10-06 (register B04): an answer can only be judged against the question
and rubric it was given to. checkpoint_attempt.quiz_snapshot_json holds one wording per
sitting, taken when the sitting ends -- but a sitting's answers can be weeks apart
(question handed back after a report) and the question may have been rewritten in
between. In the export of 2026-10-06 the wording of 201 of 705 answers could not be
established.

    checkpoint_answer.question_snapshot_json   the question dict as it read when the
                                               answer was given; NULL on older rows

Nothing is backfilled: for old rows the wording is not known, and writing the sitting's
in would state as fact what is only a guess.
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
    ('checkpoint_answer', 'question_snapshot_json',
     "ALTER TABLE checkpoint_answer ADD COLUMN question_snapshot_json TEXT"),
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
