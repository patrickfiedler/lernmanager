"""Names on teacher accounts.

Patrick, 2026-10-28: teachers get a pool login like students ('agilebear'), so
the Lehrkräfte list needs the person's name next to it, and the credentials PDF
prints it.

    admin.nachname, admin.vorname   NULL for accounts created before this
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
    ('admin', 'nachname', "ALTER TABLE admin ADD COLUMN nachname TEXT"),
    ('admin', 'vorname', "ALTER TABLE admin ADD COLUMN vorname TEXT"),
]


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        for table, column, statement in NEW_COLUMNS:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column in cols:
                print(f"  {table}.{column} already exists, skipping.")
                continue
            conn.execute(statement)
            print(f"  Added {table}.{column}.")
        conn.commit()
        print("Done.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
