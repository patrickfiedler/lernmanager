"""Make grading_run.klasse_id nullable + add UNIQUE(job_id).

Multi-class + chunked grading upload redesign (todo.md § Graded Artifacts,
2026-08-17): a single upload can now span students from several classes (or
none known at all, for a scan-folders-originated run whose callback arrives
before any Lernmanager-side registration). klasse_id NOT NULL no longer
holds.

UNIQUE(job_id) closes a related gap: the results callback (app.py
/internal/grading/results -> models.import_grading_callback) now
auto-creates a grading_run when none exists yet for that job_id. Without a
uniqueness guarantee, a retried callback delivery (the grading service's
callback is fire-and-forget, spec §4) could race past the "does a run
already exist" check and create two rows for the same job.

SQLite can't drop a NOT NULL/add a constraint via ALTER TABLE, so this is a
table rebuild: FK enforcement off for the swap (grading_result has ON DELETE
CASCADE to grading_run.id -- a naive drop with FKs on would cascade-delete
every result row), copy, drop, rename, re-enable FKs, verify with
PRAGMA foreign_key_check. Pattern matches migrate_013.

Ref: Lernmanager/todo.md § Graded Artifacts; grading-service-deployment.md.
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(grading_run)").fetchall()}
        if not cols:
            print("Table 'grading_run' does not exist, skipping (run migrate_040 first).")
            return

        already_nullable = any(
            row[1] == 'klasse_id' and row[3] == 0  # notnull flag
            for row in conn.execute("PRAGMA table_info(grading_run)").fetchall()
        )
        if already_nullable:
            print("grading_run.klasse_id is already nullable, skipping.")
            return

        before_count = conn.execute("SELECT COUNT(*) FROM grading_run").fetchone()[0]

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("""
                CREATE TABLE grading_run_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    klasse_id INTEGER,
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
                    UNIQUE(job_id),
                    FOREIGN KEY (klasse_id) REFERENCES klasse(id),
                    FOREIGN KEY (task_id) REFERENCES task(id)
                )
            """)
            conn.execute("""
                INSERT INTO grading_run_new
                    (id, job_id, klasse_id, task_id, rubric, provider, model,
                     imported_at, graded_at, total_students, flagged_count,
                     zero_score_count, media_purged_at)
                SELECT id, job_id, klasse_id, task_id, rubric, provider, model,
                       imported_at, graded_at, total_students, flagged_count,
                       zero_score_count, media_purged_at
                FROM grading_run
            """)
            conn.execute("DROP TABLE grading_run")
            conn.execute("ALTER TABLE grading_run_new RENAME TO grading_run")
            conn.execute("CREATE INDEX idx_grading_run_klasse ON grading_run(klasse_id)")
            conn.execute("CREATE INDEX idx_grading_run_task ON grading_run(task_id)")

            conn.commit()

            after_count = conn.execute("SELECT COUNT(*) FROM grading_run").fetchone()[0]
            if after_count != before_count:
                raise RuntimeError(f"Row count mismatch: {before_count} -> {after_count}")

        except Exception:
            conn.rollback()
            print("Error during grading_run rebuild -- restoring backup.")
            conn.close()
            shutil.copy2(backup_path, DATABASE)
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            print(f"WARNING: {len(violations)} FK violations after rebuild:")
            for v in violations[:10]:
                print(f"  {v}")
        else:
            print("Foreign key integrity OK.")

        print(f"grading_run.klasse_id is now nullable, UNIQUE(job_id) added ({after_count} rows preserved).")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
