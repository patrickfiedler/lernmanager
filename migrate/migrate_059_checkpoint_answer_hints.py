"""Record the AI hint a student saw after a wrong checkpoint answer.

After a wrong short_answer the page asks for a hint in a second call
(app.student_checkpoint_ai_hint): the model picks one of the authored hints, adapts it
to the answer, or says the student should report the question. Agreed with chemie in
docs/shared/requests/2026-09-13-lernmanager-zur-abstimmung-tipps-je-frage-als-material-
fuer-gezielte-ki.md.

Chemie made the log a precondition: without knowing which hint went with which failed
attempt, a weak hint cannot be told apart from a hard question. So every hint lands on
the answer row it answers. Whether the NEXT attempt was right is not stored -- it is the
next row, and the export derives it (naechster_versuch_richtig).

Columns on checkpoint_answer, all NULL for rows without a hint request:
    hint_text            what the student was shown
    hint_gap             the gap the model named first -- teacher-only, never shown
    hint_basis           1-based index of the authored hint it adapted, NULL = own wording
    hint_source          'frage' (question hints) or 'checkpoint' (checkpoint_hints)
    hint_status          pending | ok | melden | error | limit
    hint_prompt_version  llm_grading.prompt_version_for(CHECKPOINT_HINT_PROMPT)
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
    ('checkpoint_answer', 'hint_text',
     "ALTER TABLE checkpoint_answer ADD COLUMN hint_text TEXT"),
    ('checkpoint_answer', 'hint_gap',
     "ALTER TABLE checkpoint_answer ADD COLUMN hint_gap TEXT"),
    ('checkpoint_answer', 'hint_basis',
     "ALTER TABLE checkpoint_answer ADD COLUMN hint_basis INTEGER"),
    ('checkpoint_answer', 'hint_source',
     "ALTER TABLE checkpoint_answer ADD COLUMN hint_source TEXT"),
    ('checkpoint_answer', 'hint_status',
     "ALTER TABLE checkpoint_answer ADD COLUMN hint_status TEXT"),
    ('checkpoint_answer', 'hint_prompt_version',
     "ALTER TABLE checkpoint_answer ADD COLUMN hint_prompt_version TEXT"),
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
