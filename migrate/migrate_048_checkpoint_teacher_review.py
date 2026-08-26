"""Teacher-review fields for Chemie Quiz-checkpoints, plus a prompt-version stamp.

Closes the two schema gaps chemie flagged 2026-08-25 (see todo.md) before the
teacher-review UI was designed, on their explicit reasoning that a teacher's
verdict "exists only in the moment of review" and cannot be reconstructed later.

Two separate concerns, deliberately stored on two different tables:

1. **The grade** lives on checkpoint_attempt (teacher_score/teacher_note/
   reviewed_at/reviewed_by). teacher_score overrides the computed `score` --
   read via models.effective_checkpoint_score(), never by reading `score`
   directly, so the override rule exists in exactly one place. Nothing consumes
   `score` yet (the Kern-Sperre/Punktekonto computation is not built), so this
   is additive with no behaviour change today.

2. **Prompt calibration** lives on checkpoint_answer (teacher_verdict/
   teacher_note). teacher_verdict stores what the teacher says the answer
   *actually* was (0/1/NULL), not a "the LLM was wrong" boolean -- keeping both
   judgments side by side is what makes `teacher_verdict != correct` a usable
   disagreement signal in the export. It never feeds the score: a score
   correction is a grading act, a verdict is a measurement of the LLM.

prompt_version stamps which system prompt graded each answer. Without it, a
prompt change (like CHECKPOINT_SYSTEM_PROMPT on 2026-08-25) silently makes old
and new rows incomparable for calibration. The value is derived from a hash of
the prompt text (llm_grading.prompt_version_for), not a hand-maintained
constant -- it cannot drift because someone forgot to bump it. Existing rows
stay NULL: they were graded before stamping existed and there is no honest way
to reconstruct which prompt text was live at the time.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

# (table, column, statement) -- all nullable, so plain ADD COLUMN is safe and no
# table rebuild is needed (unlike migrate_047, which had to drop an FK constraint).
# The statements are written out in full rather than assembled from the table and
# column names: tests/test_schema_parity.py greps migrate/*.py for literal
# "ALTER TABLE <t> ADD COLUMN <c>" text to prove every init_db() column has a
# migration behind it, and a dynamically built string is invisible to that check.
NEW_COLUMNS = [
    ('checkpoint_attempt', 'teacher_score',
     "ALTER TABLE checkpoint_attempt ADD COLUMN teacher_score INTEGER"),
    ('checkpoint_attempt', 'teacher_note',
     "ALTER TABLE checkpoint_attempt ADD COLUMN teacher_note TEXT"),
    ('checkpoint_attempt', 'reviewed_at',
     "ALTER TABLE checkpoint_attempt ADD COLUMN reviewed_at TEXT"),
    ('checkpoint_attempt', 'reviewed_by',
     "ALTER TABLE checkpoint_attempt ADD COLUMN reviewed_by INTEGER"),
    ('checkpoint_answer', 'teacher_verdict',
     "ALTER TABLE checkpoint_answer ADD COLUMN teacher_verdict INTEGER"),
    ('checkpoint_answer', 'teacher_note',
     "ALTER TABLE checkpoint_answer ADD COLUMN teacher_note TEXT"),
    ('checkpoint_answer', 'prompt_version',
     "ALTER TABLE checkpoint_answer ADD COLUMN prompt_version TEXT"),
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

        for table in ('checkpoint_attempt', 'checkpoint_answer'):
            if table not in existing_tables:
                print(f"Table '{table}' does not exist, skipping (run migrate_047 first).")
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

        # Review queries filter on "not yet reviewed" across the whole table, so
        # the partial index only carries the rows that can still match.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoint_attempt_unreviewed
            ON checkpoint_attempt(timestamp) WHERE teacher_score IS NULL
        """)

        conn.commit()
        print(f"Migration complete ({added} column(s) added).")

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            print(f"WARNING: {len(violations)} FK violations after migration:")
            for v in violations[:10]:
                print(f"  {v}")
        else:
            print("Foreign key integrity OK.")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
