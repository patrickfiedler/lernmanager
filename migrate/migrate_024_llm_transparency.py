#!/usr/bin/env python3
"""
Database Migration: Add LLM transparency mode settings

Adds llm_transparency_mode to student (opt-in boolean) and klasse
(three-state override: NULL=no override, 0=force off, 1=force on).
"""

import os
import sys
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'


def migrate():
    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    if sqlcipher_key:
        try:
            from sqlcipher3 import dbapi2 as sqlite3
        except ImportError:
            print("✗ sqlcipher3 not installed")
            sys.exit(1)
    else:
        import sqlite3

    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        sys.exit(1)

    print("=" * 70)
    print("Migration 024: Add LLM transparency mode")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    if sqlcipher_key:
        conn.execute(f"PRAGMA key = '{sqlcipher_key}'")
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()

    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(student)")
    student_cols = [row[1] for row in cursor.fetchall()]
    cursor.execute("PRAGMA table_info(klasse)")
    klasse_cols = [row[1] for row in cursor.fetchall()]

    if 'llm_transparency_mode' in student_cols and 'llm_transparency_mode' in klasse_cols:
        print("✓ Columns already exist — migration already applied")
        conn.close()
        return

    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup: {backup_path}")

    if 'llm_transparency_mode' not in student_cols:
        cursor.execute("ALTER TABLE student ADD COLUMN llm_transparency_mode INTEGER DEFAULT 0")
        print("✓ Added student.llm_transparency_mode")

    if 'llm_transparency_mode' not in klasse_cols:
        cursor.execute("ALTER TABLE klasse ADD COLUMN llm_transparency_mode INTEGER DEFAULT NULL")
        print("✓ Added klasse.llm_transparency_mode")

    conn.commit()
    conn.close()
    print("\nMigration completed successfully!")


if __name__ == '__main__':
    migrate()
