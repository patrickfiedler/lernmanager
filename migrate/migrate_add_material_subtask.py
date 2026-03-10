#!/usr/bin/env python3
"""Migration: Add material_subtask join table for per-Aufgabe material assignments.

Run BEFORE deploying code changes:
    python migrate_add_material_subtask.py
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

    # Check if table already exists
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='material_subtask'"
    ).fetchone()

    if existing:
        print("Table material_subtask already exists. Nothing to do.")
        conn.close()
        return

    conn.executescript('''
        CREATE TABLE material_subtask (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            subtask_id INTEGER NOT NULL,
            UNIQUE(material_id, subtask_id),
            FOREIGN KEY (material_id) REFERENCES material(id) ON DELETE CASCADE,
            FOREIGN KEY (subtask_id) REFERENCES subtask(id) ON DELETE CASCADE
        );
    ''')

    conn.commit()
    conn.close()
    print("Created material_subtask table.")


if __name__ == '__main__':
    migrate()
