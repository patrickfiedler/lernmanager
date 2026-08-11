"""Clayden-style unit Connections (Chemie/MBI cross-project proposal).

Adds:
  - task.unit_slug: stable author-chosen string ID (e.g. "modul_01"),
    global+UNIQUE, referenced by other units' building_on entries. Content
    is authored before DB import, so nothing in the content itself can
    reference a DB-assigned task.id yet.
  - task.connections_json: JSON {"building_on": [...], "arriving_at": [...]}.
    building_on entries: {label, unit?, strength?} - unit is a resolvable
    unit_slug reference (omit for external/non-Lernmanager prerequisites,
    free-text label only), strength is "hard"|"soft" (default "hard").
    arriving_at: array of 2-3 short narrative strings (orientation gist,
    not the same as the still-proposed lernziele tracking field).
    looking_forward_to is NOT stored - computed as the inverse of
    building_on across the whole library at render time (avoids two
    authors/files drifting out of sync).

Contract: docs/shared/chemie/technical.md § Proposed cross-project
enhancement: Clayden-style prerequisites frontmatter.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        task_columns = [row[1] for row in conn.execute("PRAGMA table_info(task)").fetchall()]

        if 'unit_slug' not in task_columns:
            conn.execute("ALTER TABLE task ADD COLUMN unit_slug TEXT")
            print("Added 'unit_slug' column to task table.")
        else:
            print("Column 'unit_slug' already exists on task, skipping.")

        if 'connections_json' not in task_columns:
            conn.execute("ALTER TABLE task ADD COLUMN connections_json TEXT")
            print("Added 'connections_json' column to task table.")
        else:
            print("Column 'connections_json' already exists on task, skipping.")

        existing_index = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_task_unit_slug'"
        ).fetchone()[0]
        if existing_index:
            print("Unique index 'idx_task_unit_slug' already exists, skipping.")
        else:
            conn.execute("""
                CREATE UNIQUE INDEX idx_task_unit_slug
                ON task(unit_slug)
                WHERE unit_slug IS NOT NULL
            """)
            print("Added partial unique index 'idx_task_unit_slug' (NULLs allowed, non-NULL must be unique).")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
