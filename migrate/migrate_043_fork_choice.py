"""Fork/Choice Artifact Model schema (MBI Kl.6 Unit 1 branching capstone).

Adds:
  - subtask.fork_group: groups subtasks (across branches) into one fork/choice
    decision point
  - subtask.fork_branch: which branch within fork_group this subtask belongs to
  - subtask.fork_branch_label: student-facing branch name, set once on the
    branch's first subtask
  - subtask.fork_branch_note: optional steering note shown on the selection
    screen
  - subtask.fork_required: 1 (default) = mandatory choice; 0 = enrichment fork,
    unpicked branches stay reachable as Zusatz
  - student_fork_choice: one row per student per fork_group, records the
    chosen branch

Design doc: docs/shared/lernmanager/fork-choice-artifact-model.md
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

        if 'fork_group' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN fork_group TEXT")
            print("Added 'fork_group' column to subtask table.")
        else:
            print("Column 'fork_group' already exists on subtask, skipping.")

        if 'fork_branch' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN fork_branch TEXT")
            print("Added 'fork_branch' column to subtask table.")
        else:
            print("Column 'fork_branch' already exists on subtask, skipping.")

        if 'fork_branch_label' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN fork_branch_label TEXT")
            print("Added 'fork_branch_label' column to subtask table.")
        else:
            print("Column 'fork_branch_label' already exists on subtask, skipping.")

        if 'fork_branch_note' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN fork_branch_note TEXT")
            print("Added 'fork_branch_note' column to subtask table.")
        else:
            print("Column 'fork_branch_note' already exists on subtask, skipping.")

        if 'fork_required' not in subtask_columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN fork_required INTEGER NOT NULL DEFAULT 1")
            print("Added 'fork_required' column to subtask table.")
        else:
            print("Column 'fork_required' already exists on subtask, skipping.")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS student_fork_choice (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                fork_group TEXT NOT NULL,
                fork_branch TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(student_id, fork_group),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            )
        """)
        print("Created 'student_fork_choice' table.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
