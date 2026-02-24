#!/usr/bin/env python3
"""
Database Migration 008: Add session_type to warmup_session table

Differentiates daily warmup sessions from student-initiated practice sessions.
Existing rows get the default value 'warmup' (close enough for historical data).
"""

import os
import sys
import shutil
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        print("  Run from project root directory")
        sys.exit(1)

    import sqlite3

    print("=" * 70)
    print("Migration 008: Add session_type to warmup_session table")
    print("=" * 70)

    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\nStep 2: Checking if column already exists...")
    cursor.execute("PRAGMA table_info(warmup_session)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'session_type' in columns:
        print("✓ Column 'session_type' already exists — already applied")
        conn.close()
        return

    print("\nStep 3: Adding session_type column...")
    try:
        cursor.execute("ALTER TABLE warmup_session ADD COLUMN session_type TEXT NOT NULL DEFAULT 'warmup'")
        conn.commit()
        print("✓ Column added (existing rows default to 'warmup')")
    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)

    print("\nStep 4: Verifying...")
    cursor.execute("PRAGMA table_info(warmup_session)")
    columns = [row[1] for row in cursor.fetchall()]
    assert 'session_type' in columns, "Column not found after migration"
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 008 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
