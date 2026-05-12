#!/usr/bin/env python3
"""
Database Migration 025: Artifact gate

Adds:
  - subtask.artifact_gate_json: deterministic gate config per capstone task
  - student_subtask.artifact_gate_passed: per-student gate result
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
    print("Migration 025: Artifact gate")
    print("=" * 70)

    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("\nStep 2: Adding artifact_gate_json to subtask...")
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'artifact_gate_json' in columns:
        print("✓ Column already exists — skipping")
    else:
        cursor.execute("ALTER TABLE subtask ADD COLUMN artifact_gate_json TEXT")
        conn.commit()
        print("✓ Column added")

    print("\nStep 3: Adding artifact_gate_passed to student_subtask...")
    cursor.execute("PRAGMA table_info(student_subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'artifact_gate_passed' in columns:
        print("✓ Column already exists — skipping")
    else:
        cursor.execute("ALTER TABLE student_subtask ADD COLUMN artifact_gate_passed INTEGER DEFAULT NULL")
        conn.commit()
        print("✓ Column added")

    print("\nStep 4: Verifying...")
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    assert 'artifact_gate_json' in columns
    cursor.execute("PRAGMA table_info(student_subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    assert 'artifact_gate_passed' in columns
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 025 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
