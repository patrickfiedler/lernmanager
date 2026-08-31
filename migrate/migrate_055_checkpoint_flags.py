"""Let a student report one checkpoint question as broken, and let a teacher rule on it.

Two things ship here, and they are separate on purpose.

`checkpoint_flag` is keyed on (checkpoint_id, question_index) -- a claim about the
QUESTION, not about one student's answer. A broken question is broken for all 24
students; putting the teacher's verdict on checkpoint_answer would mean marking the
same question once per student and would make "which questions are broken?"
unanswerable. Student reports and teacher verdicts share the table because they are
the same object seen from two sides: the student raises it, the teacher closes it.

`checkpoint_attempt.question_scores_json` is the per-question 0/2/3 breakdown behind
the session score. It was never stored -- only the min() survived -- which is why a
finished attempt could be overridden by hand but never recomputed. A flagged question
carries `null` (no score, pending a human), and rescoring after a rejected flag is
"replace one entry, re-min" instead of rebuilding the session from the answer log
(where per-question hint counts are not exactly recoverable).

Deliberately NOT reusing existing fields, both of which already mean something else:
- `checkpoint_attempt.needs_review` means "LLM grading was unavailable, this 0 is
  fake". Flags get their own badge and filter.
- `checkpoint_answer.teacher_note` is the prompt-tuning note and ships as
  `lehrer_notiz_antwort` in the calibration export. A question-design note in there
  would mix two datasets with nothing to tell them apart.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

# Written out in full rather than assembled from table/column names:
# tests/test_schema_parity.py greps migrate/*.py for the literal statement text,
# and a built string is invisible to it.
CREATE_FLAG_TABLE = """
CREATE TABLE IF NOT EXISTS checkpoint_flag (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id INTEGER NOT NULL,
    question_index INTEGER NOT NULL,
    student_id INTEGER,
    checkpoint_attempt_id INTEGER,
    session_uid TEXT,
    source TEXT NOT NULL,
    reason_code TEXT,
    reason_text TEXT,
    question_text_at_flag TEXT,
    status TEXT NOT NULL DEFAULT 'offen',
    resolution_note TEXT,
    resolved_at TEXT,
    resolved_by INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_checkpoint_flag_question ON checkpoint_flag(checkpoint_id, question_index)",
    "CREATE INDEX IF NOT EXISTS idx_checkpoint_flag_attempt ON checkpoint_flag(checkpoint_attempt_id)",
    "CREATE INDEX IF NOT EXISTS idx_checkpoint_flag_open ON checkpoint_flag(created_at) WHERE status = 'offen'",
]

NEW_COLUMNS = [
    ('checkpoint_attempt', 'question_scores_json',
     "ALTER TABLE checkpoint_attempt ADD COLUMN question_scores_json TEXT"),
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
            print("Table 'checkpoint_attempt' does not exist, skipping.")
            return

        if 'checkpoint_flag' in existing_tables:
            print("  Table checkpoint_flag already exists, skipping.")
        else:
            conn.execute(CREATE_FLAG_TABLE)
            print("  Created table checkpoint_flag.")
        for statement in INDEXES:
            conn.execute(statement)

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
        # Existing rows keep question_scores_json = NULL. That is correct and not a
        # gap: those sessions predate flags, nothing can be flagged in them, and the
        # stored `score` is still the whole truth about them.
        print(f"\nDone. {added} column(s) added.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
