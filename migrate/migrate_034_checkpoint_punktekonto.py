"""Checkpoint-Punktekonto Core log (Chemie 11/12 grading model).

Adds:
  - task.module_tier: kern_standard (default) / hero — swap-rule tier, see
    docs/shared/lernmanager/chemie-data-contract.md § 7
  - subtask.checkpoint_type: quiz / abnahme / artefakt (NULL = not a checkpoint)
  - subtask.kern_standard_tag: kern / standard (NULL = not a checkpoint)
  - checkpoint_attempt: per-student, per-completed-checkpoint log. One row per
    completion, not per submission (attempt_count/hint_count absorb retries).

Contract: docs/shared/lernmanager/chemie-data-contract.md (agreed 2026-08-09,
commit 4d837b7 lifted the build gate).
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
        if 'module_tier' not in task_columns:
            conn.execute("ALTER TABLE task ADD COLUMN module_tier TEXT NOT NULL DEFAULT 'kern_standard'")
            print("Added 'module_tier' column to task table.")
        else:
            print("Column 'module_tier' already exists on task, skipping.")

        subtask_columns = [row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()]
        if 'checkpoint_type' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN checkpoint_type TEXT")
            print("Added 'checkpoint_type' column to subtask table.")
        else:
            print("Column 'checkpoint_type' already exists on subtask, skipping.")
        if 'kern_standard_tag' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN kern_standard_tag TEXT")
            print("Added 'kern_standard_tag' column to subtask table.")
        else:
            print("Column 'kern_standard_tag' already exists on subtask, skipping.")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoint_attempt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                checkpoint_id INTEGER NOT NULL,
                module_id INTEGER NOT NULL,
                checkpoint_type TEXT NOT NULL,
                kern_standard_tag TEXT NOT NULL,
                score INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                hint_count INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (checkpoint_id) REFERENCES subtask(id) ON DELETE CASCADE,
                FOREIGN KEY (module_id) REFERENCES task(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoint_attempt_student_module
            ON checkpoint_attempt(student_id, module_id)
        """)
        print("Created 'checkpoint_attempt' table and index.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
