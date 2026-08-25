"""Per-question answer log for Chemie Quiz-checkpoints, plus two fixes so a
graded checkpoint result can no longer be silently destroyed.

Background: checkpoint_attempt only ever stored the aggregate 0/2/3 score,
never the student's actual answer text or the LLM's feedback for any
question -- that data lived only in the Flask session during the live
session and was discarded the instant the checkpoint finished. Requested by
Patrick 2026-08-25 ahead of a planned teacher-review UI ("nothing is lost").
Advisor-reviewed (opus) before building -- see conversation for full
reasoning; two design points worth recording here:

1. **Log every attempt, not just the final answer** (checkpoint_answer,
   new table). The score's whole meaning is 3 = right first try vs.
   2 = right after retry/hint -- only the attempt-by-attempt log can show
   which. Rows are written as answers happen (checkpoint_id may not have a
   checkpoint_attempt yet -- see session_uid below), then backfilled with
   checkpoint_attempt_id once the session finishes.

2. **Snapshot the quiz JSON on checkpoint_attempt** (quiz_snapshot_json).
   Content can be edited later and subtasks are matched by *position* on
   re-import (see update_subtasks docs), so a stored question_index can
   silently point at a different question than the one actually answered.
   The regular-quiz review page (get_text_quiz_answers) already has a
   literal '(Frage nicht mehr verfügbar)' fallback for this exact problem --
   don't repeat it here.

Two existing silent-deletion paths would otherwise destroy this log too
(Patrick's explicit calls, both "keep it"/"survive it"):

- **Re-import "Fortschritte zurücksetzen"** (models.reset_student_progress_
  for_task, called only when the admin opts into that checkbox on overwrite-
  import) used to hard-DELETE checkpoint_attempt rows for the module. Now
  soft-deletes via `superseded_at` instead -- the grade record survives, but
  has_passed_subtask_quiz (the progression-gate check) ignores superseded
  rows so re-checking that gate after a reset behaves exactly as before
  (this is what commit f9d6a24 fixed originally -- a stale "already passed"
  gate after re-import -- soft-delete preserves that fix while also
  preserving the data).
- **Deleting/editing away an Aufgabe** cascade-deleted checkpoint_attempt
  via `ON DELETE CASCADE` on checkpoint_id (subtask FK), because
  PRAGMA foreign_keys=ON (models.py). Rebuilt without a FK constraint on
  checkpoint_id in either table -- the row (and its quiz_snapshot_json /
  answer text) now survives the Aufgabe being deleted; a review UI just
  needs to handle "Aufgabe existiert nicht mehr" (already the norm
  elsewhere in this codebase, see get_text_quiz_answers).

student_id/module_id keep their existing cascades (student deleted -> their
records go; whole Thema deleted -> its checkpoint records go) -- only the
Aufgabe-level (subtask) link was the problem.
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(checkpoint_attempt)").fetchall()}
        if not cols:
            print("Table 'checkpoint_attempt' does not exist, skipping (run migrate_034 first).")
            return

        if 'superseded_at' in cols and 'quiz_snapshot_json' in cols:
            print("checkpoint_attempt already rebuilt, skipping table rebuild.")
        else:
            before_count = conn.execute("SELECT COUNT(*) FROM checkpoint_attempt").fetchone()[0]

            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                conn.execute("""
                    CREATE TABLE checkpoint_attempt_new (
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
                        needs_review INTEGER NOT NULL DEFAULT 0,
                        review_notes TEXT,
                        quiz_snapshot_json TEXT,
                        superseded_at TEXT,
                        FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                        FOREIGN KEY (module_id) REFERENCES task(id) ON DELETE CASCADE
                    )
                """)
                # checkpoint_id deliberately has no FK constraint below -- see module
                # docstring point 2. It's a plain reference to subtask.id that may
                # point at nothing once an Aufgabe is deleted; quiz_snapshot_json is
                # what makes the row still readable when that happens.
                conn.execute("""
                    INSERT INTO checkpoint_attempt_new
                        (id, student_id, checkpoint_id, module_id, checkpoint_type,
                         kern_standard_tag, score, attempt_count, hint_count, timestamp,
                         needs_review, review_notes)
                    SELECT id, student_id, checkpoint_id, module_id, checkpoint_type,
                           kern_standard_tag, score, attempt_count, hint_count, timestamp,
                           needs_review, review_notes
                    FROM checkpoint_attempt
                """)
                conn.execute("DROP TABLE checkpoint_attempt")
                conn.execute("ALTER TABLE checkpoint_attempt_new RENAME TO checkpoint_attempt")
                conn.execute("CREATE INDEX idx_checkpoint_attempt_student_module ON checkpoint_attempt(student_id, module_id)")
                conn.execute("CREATE INDEX idx_checkpoint_attempt_checkpoint ON checkpoint_attempt(checkpoint_id)")

                conn.commit()

                after_count = conn.execute("SELECT COUNT(*) FROM checkpoint_attempt").fetchone()[0]
                if after_count != before_count:
                    raise RuntimeError(f"Row count mismatch: {before_count} -> {after_count}")

            except Exception:
                conn.rollback()
                print("Error during checkpoint_attempt rebuild -- restoring backup.")
                conn.close()
                shutil.copy2(backup_path, DATABASE)
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")

            print(f"Rebuilt 'checkpoint_attempt' with quiz_snapshot_json/superseded_at, no FK on checkpoint_id ({after_count} rows preserved).")

        existing_tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        if 'checkpoint_answer' not in existing_tables:
            # checkpoint_attempt_id is nullable: an answer is written the moment it's
            # graded, before the session finishes and checkpoint_attempt is created
            # (see student_checkpoint_answer / student_checkpoint_finish). session_uid
            # correlates rows within one sitting so they can be backfilled with the
            # real checkpoint_attempt_id once it exists. Neither checkpoint_id nor
            # checkpoint_attempt_id carries ON DELETE CASCADE -- see module docstring.
            conn.execute("""
                CREATE TABLE checkpoint_answer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkpoint_attempt_id INTEGER,
                    student_id INTEGER NOT NULL,
                    checkpoint_id INTEGER NOT NULL,
                    session_uid TEXT NOT NULL,
                    question_index INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    answer_text TEXT,
                    correct INTEGER,
                    feedback TEXT,
                    grader TEXT NOT NULL,
                    llm_model TEXT,
                    hints_used_before INTEGER NOT NULL DEFAULT 0,
                    gave_up INTEGER NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX idx_checkpoint_answer_attempt ON checkpoint_answer(checkpoint_attempt_id)")
            conn.execute("CREATE INDEX idx_checkpoint_answer_session ON checkpoint_answer(session_uid)")
            conn.execute("CREATE INDEX idx_checkpoint_answer_student_checkpoint ON checkpoint_answer(student_id, checkpoint_id)")
            conn.commit()
            print("Created 'checkpoint_answer' table + indexes.")
        else:
            print("Table 'checkpoint_answer' already exists, skipping.")

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            print(f"WARNING: {len(violations)} FK violations after migration:")
            for v in violations[:10]:
                print(f"  {v}")
        else:
            print("Foreign key integrity OK.")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
