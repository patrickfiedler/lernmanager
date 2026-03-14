#!/usr/bin/env python3
"""
Database Migration: Warmup / Spaced Repetition Tables

Creates:
  - warmup_history: per-student per-question stats (streak, times_shown, etc.)
  - warmup_session: log of each warmup/practice session

Must run BEFORE deploying warmup feature code.
"""

import os
import sys
import shutil
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'


def get_sqlite(sqlcipher_key):
    """Return the appropriate sqlite3 module."""
    if sqlcipher_key:
        try:
            from sqlcipher3 import dbapi2 as sqlite3
            return sqlite3
        except ImportError:
            print("✗ sqlcipher3 not installed")
            print("  Install with: pip install sqlcipher3-binary")
            sys.exit(1)
    else:
        import sqlite3
        return sqlite3


def connect(sqlite3, sqlcipher_key):
    """Connect to the database and verify access."""
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


def table_exists(conn, table_name):
    """Check if a table exists."""
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row['cnt'] > 0


def main():
    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    sqlite3 = get_sqlite(sqlcipher_key)

    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found at {DB_PATH}")
        sys.exit(1)

    print("=" * 50)
    print("Migration: Warmup / Spaced Repetition Tables")
    print("=" * 50)

    # Step 1: Backup
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f'{DB_PATH}.backup_{timestamp}'
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = connect(sqlite3, sqlcipher_key)

    try:
        # Step 2: Create warmup_history table
        if table_exists(conn, 'warmup_history'):
            print("⚠ warmup_history table already exists, skipping")
        else:
            conn.execute('''
                CREATE TABLE warmup_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    task_id INTEGER,
                    subtask_id INTEGER,
                    question_index INTEGER NOT NULL,
                    times_shown INTEGER NOT NULL DEFAULT 0,
                    times_correct INTEGER NOT NULL DEFAULT 0,
                    last_shown DATE,
                    streak INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(student_id, task_id, subtask_id, question_index),
                    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
                )
            ''')
            conn.execute('''
                CREATE INDEX idx_warmup_student
                ON warmup_history(student_id, last_shown)
            ''')
            print("✓ Created warmup_history table + index")

        # Step 3: Create warmup_session table
        if table_exists(conn, 'warmup_session'):
            print("⚠ warmup_session table already exists, skipping")
        else:
            conn.execute('''
                CREATE TABLE warmup_session (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    questions_shown INTEGER NOT NULL DEFAULT 0,
                    questions_correct INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
                )
            ''')
            print("✓ Created warmup_session table")

        conn.commit()

        # Step 4: Verify
        assert table_exists(conn, 'warmup_history'), "warmup_history not found after migration"
        assert table_exists(conn, 'warmup_session'), "warmup_session not found after migration"
        print("✓ Verification passed")

        print("\n" + "=" * 50)
        print("Migration complete!")
        print(f"Backup at: {backup_path}")
        print("Next: Deploy warmup feature code")
        print("=" * 50)

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        print(f"Restoring from backup: {backup_path}")
        conn.close()
        shutil.copy2(backup_path, DB_PATH)
        print("✓ Database restored")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
