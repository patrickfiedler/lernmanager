"""Add grading_run / grading_result tables (grading-service-deployment.md §7/§10 Phase 2).

grading_run: one row per batch imported from the grading service (klasse +
task + rubric + provider/model + import counts).

grading_result: one row per student within a grading_run. Carries the
teacher-review state machine from spec §7 (imported -> under_review -> active,
with corrected/discarded/superseded side states) and the per-criterion scores
as a JSON blob (criteria_json) -- same style as this codebase's existing
quiz_json/feedback_json/connections_json columns.

task_id is denormalized onto grading_result (also present on its parent
grading_run) so a partial unique index can enforce spec §7's "at most one
active run per (student, artifact)" rule without a cross-table constraint,
which SQLite can't express directly.

Known gap, not solved here: Lernmanager's existing in-app Level 2 grading
(artifact_feedback table, graded_artifact.criteria) is not yet part of this
selection model -- that table has no status/active concept today. Spec §7
says both sources should eventually share one model; teacher-review-ui.md §8
flags this as an open unknown (whether Level 2 already has an override UI to
reconcile with). Deferred rather than guessed at.

Ref: grading-with-llm/task_plan.md sub-phase 2c.
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
        existing_tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if 'grading_run' not in existing_tables:
            conn.execute("""
                CREATE TABLE grading_run (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    klasse_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    rubric TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT,
                    imported_at TEXT NOT NULL,
                    graded_at TEXT,
                    total_students INTEGER NOT NULL DEFAULT 0,
                    flagged_count INTEGER NOT NULL DEFAULT 0,
                    zero_score_count INTEGER NOT NULL DEFAULT 0,
                    media_purged_at TEXT,
                    FOREIGN KEY (klasse_id) REFERENCES klasse(id),
                    FOREIGN KEY (task_id) REFERENCES task(id)
                )
            """)
            conn.execute("CREATE INDEX idx_grading_run_klasse ON grading_run(klasse_id)")
            conn.execute("CREATE INDEX idx_grading_run_task ON grading_run(task_id)")
            print("Created 'grading_run' table + indexes.")
        else:
            print("Table 'grading_run' already exists, skipping.")

        if 'grading_result' not in existing_tables:
            conn.execute("""
                CREATE TABLE grading_result (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    grading_run_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    student_id INTEGER,
                    netzwerk_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'imported',
                    llm_total_score REAL,
                    llm_max_score REAL,
                    teacher_total_score REAL,
                    note INTEGER,
                    flagged INTEGER NOT NULL DEFAULT 0,
                    confidence TEXT,
                    error TEXT,
                    criteria_json TEXT NOT NULL,
                    document_file TEXT,
                    media_json TEXT,
                    media_skipped_json TEXT,
                    reviewed_at TEXT,
                    released_at TEXT,
                    released_by INTEGER,
                    superseded_by_id INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(grading_run_id, netzwerk_id),
                    FOREIGN KEY (grading_run_id) REFERENCES grading_run(id) ON DELETE CASCADE,
                    FOREIGN KEY (task_id) REFERENCES task(id),
                    FOREIGN KEY (student_id) REFERENCES student(id),
                    FOREIGN KEY (released_by) REFERENCES admin(id),
                    FOREIGN KEY (superseded_by_id) REFERENCES grading_result(id)
                )
            """)
            conn.execute("CREATE INDEX idx_grading_result_run ON grading_result(grading_run_id)")
            conn.execute("CREATE INDEX idx_grading_result_student ON grading_result(student_id)")
            conn.execute("""
                CREATE UNIQUE INDEX idx_grading_result_one_active_per_artifact
                ON grading_result(student_id, task_id) WHERE status = 'active'
            """)
            print("Created 'grading_result' table + indexes.")
        else:
            print("Table 'grading_result' already exists, skipping.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
