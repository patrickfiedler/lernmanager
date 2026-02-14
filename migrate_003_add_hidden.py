#!/usr/bin/env python3
"""Migration: Add 'hidden' column to subtask table.

Simple admin override to hide specific subtasks from all students,
replacing the complex subtask_visibility management UI.

Usage:
    python migrate_add_hidden.py
"""

import os
import sys

# SQLCipher support
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
if SQLCIPHER_KEY:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
    except ImportError:
        import sqlite3
        print("WARNING: SQLCIPHER_KEY set but sqlcipher3 not installed.", file=sys.stderr)
else:
    import sqlite3

import config


def migrate():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row

    if SQLCIPHER_KEY:
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')

    conn.execute("PRAGMA foreign_keys = ON")

    # Check if column already exists
    columns = [row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()]

    if 'hidden' not in columns:
        conn.execute("ALTER TABLE subtask ADD COLUMN hidden INTEGER DEFAULT 0")
        conn.commit()
        print("Added 'hidden' column to subtask table.")
    else:
        print("Column 'hidden' already exists, skipping.")

    conn.close()
    print("Migration complete.")


if __name__ == '__main__':
    migrate()
