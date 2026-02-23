#!/usr/bin/env python3
"""
Database Migration: Fix duplicate active primary tasks

Symptoms: Students appear twice in class list, each copy showing a different
active topic. Caused by two student_task rows with abgeschlossen=0 and
rolle='primary' for the same student+class.

Changes:
  - Close all but the most recent active primary per student+class
  - Add a partial unique index to prevent recurrence

Run BEFORE or AFTER code deploy (data fix, no schema change).
"""

import os
import sys
import shutil
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'


def get_sqlite(sqlcipher_key):
    if sqlcipher_key:
        try:
            from sqlcipher3 import dbapi2 as sqlite3
            return sqlite3
        except ImportError:
            print("✗ sqlcipher3 not installed")
            sys.exit(1)
    else:
        import sqlite3
    return sqlite3


def connect(sqlite3, sqlcipher_key):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if sqlcipher_key:
        conn.execute(f"PRAGMA key = '{sqlcipher_key}'")
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            print("✗ Failed to decrypt database with provided key")
            sys.exit(1)
    return conn


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        print("  Run from the project root directory")
        sys.exit(1)

    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    sqlite3 = get_sqlite(sqlcipher_key)

    print()
    print("=" * 70)
    print("Migration: Fix duplicate active primary tasks")
    print("=" * 70)

    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"\n✓ Backup: {backup_path}")

    conn = connect(sqlite3, sqlcipher_key)

    # Step 1: Count duplicates
    duplicates = conn.execute("""
        SELECT COUNT(*) as n FROM student_task
        WHERE abgeschlossen = 0 AND rolle = 'primary'
          AND id NOT IN (
              SELECT MAX(id) FROM student_task
              WHERE abgeschlossen = 0 AND rolle = 'primary'
              GROUP BY student_id, klasse_id
          )
    """).fetchone()[0]
    print(f"\nStep 1: Found {duplicates} duplicate active primary task(s) to close")

    # Step 2: Close all but the most recent active primary per student+class
    conn.execute("""
        UPDATE student_task SET abgeschlossen = 1
        WHERE abgeschlossen = 0 AND rolle = 'primary'
          AND id NOT IN (
              SELECT MAX(id) FROM student_task
              WHERE abgeschlossen = 0 AND rolle = 'primary'
              GROUP BY student_id, klasse_id
          )
    """)
    conn.commit()
    print(f"✓ Closed {duplicates} duplicate(s) (kept most recent per student+class)")

    # Step 3: Add partial unique index to prevent recurrence
    # SQLite partial indexes (WHERE clause) enforce uniqueness only on matching rows
    existing = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_one_active_primary'"
    ).fetchone()[0]

    if existing:
        print("\nStep 2: Unique index already exists — skipping")
    else:
        conn.execute("""
            CREATE UNIQUE INDEX idx_one_active_primary
            ON student_task(student_id, klasse_id)
            WHERE abgeschlossen = 0 AND rolle = 'primary'
        """)
        conn.commit()
        print("\nStep 2: ✓ Added partial unique index (idx_one_active_primary)")
        print("         This prevents two active primary topics per student+class")

    conn.close()
    print("\n✓ Migration complete")


if __name__ == '__main__':
    migrate()
