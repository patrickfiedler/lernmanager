#!/usr/bin/env python3
"""
Database Migration: Add student-facing learning goal (lernziel_schueler)

Adds lernziel_schueler column to task table. Nullable — falls back to lernziel.
"""

import os
import sys
import shutil
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        sys.exit(1)

    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    if sqlcipher_key:
        from sqlcipher3 import dbapi2 as sqlite3
    else:
        import sqlite3

    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    if sqlcipher_key:
        conn.execute(f"PRAGMA key = '{sqlcipher_key}'")

    columns = [row[1] for row in conn.execute("PRAGMA table_info(task)").fetchall()]

    if 'lernziel_schueler' in columns:
        print("✓ lernziel_schueler already exists")
    else:
        conn.execute("ALTER TABLE task ADD COLUMN lernziel_schueler TEXT")
        conn.commit()
        print("✓ Added task.lernziel_schueler")

    conn.close()
    print("Done.")


if __name__ == '__main__':
    migrate()
