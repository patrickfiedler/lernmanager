#!/usr/bin/env python3
"""
Database Migration 032: Student artifact file storage

Adds:
  - student_artifact_file: latest uploaded artifact file per (student, subtask)
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
    print("Migration 032: Student artifact file storage")
    print("=" * 70)

    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\nStep 2: Creating student_artifact_file table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_artifact_file (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subtask_id INTEGER NOT NULL,
            original_filename TEXT NOT NULL,
            disk_filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            UNIQUE(student_id, subtask_id),
            FOREIGN KEY (student_id) REFERENCES student(id),
            FOREIGN KEY (subtask_id) REFERENCES subtask(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_student_artifact_file_student_subtask
        ON student_artifact_file(student_id, subtask_id)
    """)
    conn.commit()
    print("✓ Table and index created")

    print("\nStep 3: Verifying...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='student_artifact_file'")
    assert cursor.fetchone(), "Table not found"
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 032 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
