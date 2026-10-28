"""Step ticks on the server.

Patrick, 2026-10-28: the ticks next to the numbered steps of an Aufgabe lived in
localStorage only, and school PCs wipe browser data at logout -- so every lesson
started with all ticks gone.

    step_tick   one row per (student, Aufgabe): JSON list of the ticked steps'
                text hashes (computed in templates/student/klasse.html). The page
                always sends the whole list, so the last save wins.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS step_tick (
    student_id INTEGER NOT NULL,
    subtask_id INTEGER NOT NULL,
    step_keys TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (student_id, subtask_id),
    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
    FOREIGN KEY (subtask_id) REFERENCES subtask(id) ON DELETE CASCADE
)
"""


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute(CREATE_TABLE)
        conn.commit()
        print("Done. step_tick is in place.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
