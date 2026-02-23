#!/usr/bin/env python3
"""
Database Migration 006: Add fertig_wenn column to subtask table

Extracts "✅ Fertig wenn:" sections from existing beschreibung into a dedicated
fertig_wenn column. This enables the visual "completion zone" UI where the criterion
is displayed as a styled callout directly above the checkbox.
"""

import os
import re
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
    print("Migration 006: Add fertig_wenn to subtask table")
    print("=" * 70)

    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("\nStep 2: Checking if column already exists...")
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'fertig_wenn' in columns:
        print("✓ Column 'fertig_wenn' already exists — already applied")
        conn.close()
        return

    print("\nStep 3: Adding fertig_wenn column...")
    try:
        cursor.execute("ALTER TABLE subtask ADD COLUMN fertig_wenn TEXT NULL")
        conn.commit()
        print("✓ Column added")
    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)

    print("\nStep 4: Populating from existing beschreibung...")
    rows = cursor.execute("SELECT id, beschreibung FROM subtask").fetchall()
    updated = 0
    for row in rows:
        match = re.search(r'\n+✅\s*Fertig\s+wenn:(.+)', row['beschreibung'] or '', re.DOTALL)
        if match:
            fertig_wenn = match.group(1).strip()
            new_beschreibung = (row['beschreibung'] or '')[:match.start()].rstrip()
            cursor.execute(
                "UPDATE subtask SET fertig_wenn=?, beschreibung=? WHERE id=?",
                (fertig_wenn, new_beschreibung, row['id'])
            )
            updated += 1

    conn.commit()
    print(f"✓ Populated {updated} of {len(rows)} subtasks from beschreibung")

    print("\nStep 5: Verifying...")
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    assert 'fertig_wenn' in columns, "Column not found after migration"
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 006 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
