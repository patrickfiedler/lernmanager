"""Teacher accounts next to the admin.

Patrick, 2026-10-26: colleagues get their own logins. They see only the classes
they teach and only what those classes produce; Patrick stays admin with everything.
Rules live in permissions.py.

    admin.role       'admin' (default, every existing account) or 'teacher'
    admin.active     0 = login blocked; the row stays so resolved_by & co. still resolve
    klasse_lehrer    one row = this teacher teaches this class (several per class)
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
    ('admin', 'role',
     "ALTER TABLE admin ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'"),
    ('admin', 'active',
     "ALTER TABLE admin ADD COLUMN active INTEGER NOT NULL DEFAULT 1"),
]

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS klasse_lehrer (
    klasse_id INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    PRIMARY KEY (klasse_id, admin_id),
    FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_id) REFERENCES admin(id) ON DELETE CASCADE
)
"""


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
        conn.execute(CREATE_TABLE)
        conn.commit()
        print("Done. klasse_lehrer is in place.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
