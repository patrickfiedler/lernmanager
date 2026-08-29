"""Per-class character-insert bar above free-text answer fields.

Chemie asked for this on 2026-08-29 (docs/shared/lernmanager/inbox.md § From
chemie). In the 2026-08-26 production run, the two half-equation questions
(12.2 F1/F2) drew thirty answers in eighteen distinct wordings, and not a single
one contained a reaction arrow, a subscript digit or a superscript charge.
Twenty-seven typed a substitute -- mostly "->" or "wird zu". That is not scatter,
it is a total absence: students work on iPads, and the characters are simply not
reachable from the keyboard.

One column, klasse.zeichenleiste, holding a preset key from config.CHARACTER_SETS.
NULL -- the default for every existing class -- means no bar and no change.

Why a preset key rather than free text on the class: a teacher who cannot type
these characters cannot fill a free-text field with them either. The set is
picked from a dropdown; adding a subject is a one-line change in config.py.
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
    ('klasse', 'zeichenleiste',
     "ALTER TABLE klasse ADD COLUMN zeichenleiste TEXT DEFAULT NULL"),
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
