"""Link from a Seilbahn twin to its regular topic.

MBI request 2026-08-31 (decided 2026-10-01): two topics stay two topics, linked by
`seilbahn_of: <unit_slug>` on the twin. The import stores it; nothing reads it yet.

    task.seilbahn_of   unit_slug of the regular topic, NULL for every other topic
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
    ('task', 'seilbahn_of',
     "ALTER TABLE task ADD COLUMN seilbahn_of TEXT"),
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
