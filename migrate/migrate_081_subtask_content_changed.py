"""Aufgabe: remember when its content last changed (Patrick 2026-11-15).

    subtask.content_changed_at   set by update_subtasks / update_subtasks_from_import
                                 when a field in models.SUBTASK_CONTENT_FIELDS really
                                 differs. NULL = unchanged since creation, or changed
                                 before this migration (unknown).

Updates keep a student's tick by position, so after an edit the tick may sit on
different content. A tick older than content_changed_at was made on the old
version; admin_thema_detail counts those per class.
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()}
        if 'content_changed_at' in cols:
            print("  subtask.content_changed_at already exists, skipping.")
            return
        conn.execute("ALTER TABLE subtask ADD COLUMN content_changed_at DATETIME")
        conn.commit()
        print("  Added subtask.content_changed_at.")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
