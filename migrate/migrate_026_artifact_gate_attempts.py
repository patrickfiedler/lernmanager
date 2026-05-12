#!/usr/bin/env python3
"""
Database Migration 026: Artifact gate attempt log

Adds:
  - artifact_gate_attempt: per-upload attempt log with passed + failed criteria
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
    print("Migration 026: Artifact gate attempt log")
    print("=" * 70)

    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\nStep 2: Creating artifact_gate_attempt table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS artifact_gate_attempt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subtask_id INTEGER NOT NULL,
            timestamp_local TEXT NOT NULL,
            timezone TEXT NOT NULL,
            passed INTEGER NOT NULL,
            details_json TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES student(id),
            FOREIGN KEY (subtask_id) REFERENCES subtask(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_gate_attempt_student_subtask
        ON artifact_gate_attempt(student_id, subtask_id)
    """)
    conn.commit()
    print("✓ Table and index created")

    print("\nStep 3: Verifying...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_gate_attempt'")
    assert cursor.fetchone(), "Table not found"
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 026 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
