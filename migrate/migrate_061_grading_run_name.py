"""Tell grading runs apart: a teacher-set name and how the batch was collected.

Columns, NULL for runs imported before this migration:
    grading_run.name             free text set on the run page; the list falls
                                 back to a name built from collection_json
    grading_run.collection_json  {label: value} from the header of the
                                 scan-folders log (*-log.md at the zip root):
                                 Date, Pattern(s), Class, Search Type, ...
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
    ('grading_run', 'name',
     "ALTER TABLE grading_run ADD COLUMN name TEXT"),
    ('grading_run', 'collection_json',
     "ALTER TABLE grading_run ADD COLUMN collection_json TEXT"),
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

        added = 0
        for table, column, statement in NEW_COLUMNS:
            if table not in existing_tables:
                print(f"Table '{table}' does not exist, skipping.")
                continue
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
