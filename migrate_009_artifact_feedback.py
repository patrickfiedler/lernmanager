#!/usr/bin/env python3
"""
Database Migration 009: Artifact feedback infrastructure

Creates:
  - artifact_feedback table: stores per-upload LLM checklist results
  - klasse.llm_artifact_feedback_enabled column: per-class opt-in toggle

Run before deploying code that uses artifact upload/feedback features.
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
    print("Migration 009: Artifact feedback infrastructure")
    print("=" * 70)

    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- artifact_feedback table ---
    print("\nStep 2: Creating artifact_feedback table...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_feedback'")
    if cursor.fetchone():
        print("✓ artifact_feedback table already exists — skipping")
    else:
        cursor.execute("""
            CREATE TABLE artifact_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subtask_id INTEGER NOT NULL,
                timestamp_local TEXT NOT NULL,
                timezone TEXT NOT NULL,
                feedback_json TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES student(id),
                FOREIGN KEY (subtask_id) REFERENCES subtask(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX idx_artifact_feedback_student_subtask
            ON artifact_feedback (student_id, subtask_id)
        """)
        conn.commit()
        print("✓ artifact_feedback table + index created")

    # --- klasse.llm_artifact_feedback_enabled column ---
    print("\nStep 3: Adding llm_artifact_feedback_enabled to klasse...")
    cursor.execute("PRAGMA table_info(klasse)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'llm_artifact_feedback_enabled' in columns:
        print("✓ Column already exists — skipping")
    else:
        try:
            cursor.execute(
                "ALTER TABLE klasse ADD COLUMN llm_artifact_feedback_enabled INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()
            print("✓ Column added (all existing classes default to disabled)")
        except Exception as e:
            print(f"✗ Error: {e}")
            conn.rollback()
            conn.close()
            sys.exit(1)

    # --- Verify ---
    print("\nStep 4: Verifying...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_feedback'")
    assert cursor.fetchone(), "artifact_feedback table missing"
    cursor.execute("PRAGMA table_info(klasse)")
    columns = [row[1] for row in cursor.fetchall()]
    assert 'llm_artifact_feedback_enabled' in columns, "klasse column missing"
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 009 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
