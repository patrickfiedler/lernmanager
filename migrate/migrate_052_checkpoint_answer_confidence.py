"""Record how sure the grader was, so a threshold can later be set on real data.

The model's probability for the judgment token separates good judgments from bad ones
sharply -- measured 2026-08-29 over 66 replayed answers, median 0.997 where the verdict
matched the teacher and 0.731 where it did not. A gate that lets an *uncertain rejection*
through to the teacher instead of blocking the student reached full recall without a
single extra false pass.

This migration deliberately ships only the recording, not the gate. Two reasons:

1. The threshold (0.8) was read off the same 66 cases it was scored on, and those cases
   have since been corrected -- see docs/research/2026-08-29-checkpoint-grading-
   calibration.md section 2a. It is a starting value, not an established one.
2. Acting on it changes what score_berechnet and the Kern-Sperre mean, which is a
   contract term with Chemie, not a decision Lernmanager makes alone.

Chemie is about to rewrite most of the 12.2/12.3 questions, which retires the replay
corpus. Recording confidence now means the next cohort calibrates the threshold on the
new questions by itself; recording it later means another unit's answers pass ungauged.
That is the whole reason this ships ahead of the decision it serves.

NULL is the normal value for every row no LLM graded (exact match, MC, ordering/matching,
give-up) and for any provider that returns no logprobs -- REAL NULL, never 0.0, because
"not measured" and "measured as impossible" must not collapse.
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
    ('checkpoint_answer', 'judgment_confidence',
     "ALTER TABLE checkpoint_answer ADD COLUMN judgment_confidence REAL"),
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
        if 'checkpoint_answer' not in existing_tables:
            print("Table 'checkpoint_answer' does not exist, skipping.")
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
