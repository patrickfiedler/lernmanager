"""Clear the hand-set session scores still in force (Patrick, 2026-11-24).

The review page no longer sets a session score: the points per question are the
grade (commit 01ae7c8). An override from before would keep winning over them in
effective_checkpoint_score() -- Kern-Sperre, student page, exports -- with no way
to change it. Production had exactly one.

Only teacher_score is cleared. teacher_note, student_feedback and the review mark
stay: the session was looked at, and the note is the record of why. Reset sessions
(superseded_at) keep theirs as history; they count for nothing anyway.

Each cleared row is printed, so the update log keeps what the value was.
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
        rows = conn.execute("""
            SELECT id, student_id, checkpoint_id, score, teacher_score
            FROM checkpoint_attempt
            WHERE teacher_score IS NOT NULL AND superseded_at IS NULL
        """).fetchall()
        for attempt_id, student_id, checkpoint_id, score, teacher_score in rows:
            print(f"  attempt {attempt_id} (student {student_id}, checkpoint "
                  f"{checkpoint_id}): teacher_score {teacher_score} cleared, "
                  f"computed score {score}")
        conn.execute("""
            UPDATE checkpoint_attempt SET teacher_score = NULL
            WHERE teacher_score IS NOT NULL AND superseded_at IS NULL
        """)
        conn.commit()
        print(f"Cleared {len(rows)} session score override(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
