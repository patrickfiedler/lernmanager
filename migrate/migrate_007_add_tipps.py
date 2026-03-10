#!/usr/bin/env python3
"""
Database Migration 007: Add tipps column to subtask table

Extracts "💡 Tipp:" sections from existing beschreibung into a dedicated
tipps column. This enables the collapsible "💡 Hilfe" UI shown below the
task description in the student view.
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
    print("Migration 007: Add tipps to subtask table")
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
    if 'tipps' in columns:
        print("✓ Column 'tipps' already exists — already applied")
        conn.close()
        return

    print("\nStep 3: Adding tipps column...")
    try:
        cursor.execute("ALTER TABLE subtask ADD COLUMN tipps TEXT NULL")
        conn.commit()
        print("✓ Column added")
    except Exception as e:
        print(f"✗ Error: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)

    print("\nStep 4: Populating from existing beschreibung...")
    # Each captured group = one full "💡 Tipp: ..." block including the label.
    # Leading \n* is outside the group: findall returns tip text only, while
    # sub removes blank lines before each tip too (no orphaned blank lines).
    # DOTALL lets . match \n so multi-line tips are captured in one block.
    TIP_PATTERN = re.compile(
        r'\n*(💡\s*Tipp:.+?)(?=\n\s*(?:###|🎯|📋|✅|💡)|$)',
        re.DOTALL
    )
    rows = cursor.execute("SELECT id, beschreibung FROM subtask").fetchall()
    updated = 0
    for row in rows:
        beschreibung = row['beschreibung'] or ''

        tip_matches = TIP_PATTERN.findall(beschreibung)
        if tip_matches:
            tipps = '\n'.join(m.strip() for m in tip_matches)
            new_beschreibung = TIP_PATTERN.sub('', beschreibung).rstrip()
        else:
            tipps = None
            new_beschreibung = beschreibung

        if tipps is not None:
            cursor.execute(
                "UPDATE subtask SET tipps=?, beschreibung=? WHERE id=?",
                (tipps, new_beschreibung, row['id'])
            )
            updated += 1

    conn.commit()
    print(f"✓ Populated {updated} of {len(rows)} subtasks from beschreibung")

    print("\nStep 5: Verifying...")
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    assert 'tipps' in columns, "Column not found after migration"
    print("✓ Verification passed")

    conn.close()
    print("\n" + "=" * 70)
    print("Migration 007 completed successfully!")
    print("=" * 70)


if __name__ == '__main__':
    migrate()
