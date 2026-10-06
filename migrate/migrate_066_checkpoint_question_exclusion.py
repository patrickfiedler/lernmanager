"""Take single checkpoint questions out of the grading, for everyone.

Patrick, 2026-10-06 (trigger: 1.7 "Stärken und Grenzen des Modells", three of four
questions reported by most of the course). Until now a question could only be left
out per sitting, by confirming each student's report one at a time, and whoever had
not reported it kept their points.

    checkpoint_question_exclusion   one row = this question (checkpoint_id =
                                    subtask.id, question_index) counts for nobody

Nothing stored is rewritten: the per-question scores stay as they are and every reader
skips the excluded ones (models.counted_question_scores). Deleting the row brings the
question back.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS checkpoint_question_exclusion (
    checkpoint_id INTEGER NOT NULL,
    question_index INTEGER NOT NULL,
    reason TEXT,
    question_text TEXT,
    created_at TEXT NOT NULL,
    created_by INTEGER,
    PRIMARY KEY (checkpoint_id, question_index)
)
"""


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute(CREATE_TABLE)
        conn.commit()
        print("Done. checkpoint_question_exclusion is in place.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
