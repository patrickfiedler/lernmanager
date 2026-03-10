#!/usr/bin/env python3
"""Migration: Add per-subtask quiz support.

Adds three columns:
- subtask.quiz_json TEXT — quiz JSON per Aufgabe (subtask)
- task.subtask_quiz_required INTEGER DEFAULT 1 — task-level setting
- quiz_attempt.subtask_id INTEGER — nullable (NULL = topic quiz, set = subtask quiz)

Safe to run multiple times (checks for existing columns).
"""
import models

def migrate():
    with models.db_session() as conn:
        # Check subtask columns
        subtask_cols = [r[1] for r in conn.execute("PRAGMA table_info(subtask)").fetchall()]
        if 'quiz_json' not in subtask_cols:
            conn.execute("ALTER TABLE subtask ADD COLUMN quiz_json TEXT")
            print("Added subtask.quiz_json")
        else:
            print("subtask.quiz_json already exists")

        # Check task columns
        task_cols = [r[1] for r in conn.execute("PRAGMA table_info(task)").fetchall()]
        if 'subtask_quiz_required' not in task_cols:
            conn.execute("ALTER TABLE task ADD COLUMN subtask_quiz_required INTEGER DEFAULT 1")
            print("Added task.subtask_quiz_required")
        else:
            print("task.subtask_quiz_required already exists")

        # Check quiz_attempt columns
        qa_cols = [r[1] for r in conn.execute("PRAGMA table_info(quiz_attempt)").fetchall()]
        if 'subtask_id' not in qa_cols:
            conn.execute("ALTER TABLE quiz_attempt ADD COLUMN subtask_id INTEGER")
            print("Added quiz_attempt.subtask_id")
        else:
            print("quiz_attempt.subtask_id already exists")

    print("Migration complete.")

if __name__ == '__main__':
    migrate()
