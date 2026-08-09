"""Escalating Tipp-button hints for Quiz-checkpoints (Chemie 11/12).

Adds:
  - subtask.checkpoint_hints_json: JSON array of 2-3 pre-written escalating
    hint strings (Leitfrage -> Ansatz -> Teil-Loesung), shown one at a time
    via the checkpoint session's Tipp button. Separate from the existing
    generic `tipps` field (a single always-visible pointer, not escalating).

Contract: docs/shared/lernmanager/chemie-data-contract.md §4.
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
        subtask_columns = [row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()]
        if 'checkpoint_hints_json' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN checkpoint_hints_json TEXT")
            print("Added 'checkpoint_hints_json' column to subtask table.")
        else:
            print("Column 'checkpoint_hints_json' already exists on subtask, skipping.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
