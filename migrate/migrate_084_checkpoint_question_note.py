"""A teacher's own note on a checkpoint question, autosaved (Patrick, 2026-11-24).

The Fragen view had a note field that was only stored together with a verdict
click, so a note typed without a verdict was lost. One row per teacher and
question: nobody overwrites anyone. A verdict click copies the note into the mark
(checkpoint_flag.reason_text) and deletes the row.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint_question_note (
                checkpoint_id INTEGER NOT NULL,
                question_index INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                note TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (checkpoint_id, question_index, admin_id)
            )
        """)
        conn.commit()
        print("checkpoint_question_note ready.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
