"""Who decided what on a grading run, and the way back.

Patrick, 2026-11-02: teachers review now, mistakes will happen early on. One row
per changed grading_result, with the state before and after, so a decision can
be undone alone or with its batch (batch_id). No foreign keys on purpose: the
log has to outlive a deleted run. delete_student removes a student's rows.
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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS grading_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                admin_id INTEGER,
                actor TEXT,
                action TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                grading_run_id INTEGER NOT NULL,
                run_name TEXT,
                grading_result_id INTEGER,
                student_id INTEGER,
                summary TEXT,
                before_json TEXT,
                after_json TEXT,
                undone_by INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_grading_audit_run ON grading_audit(grading_run_id);
            CREATE INDEX IF NOT EXISTS idx_grading_audit_student ON grading_audit(student_id);
        """)
        conn.commit()
        print("  grading_audit ready.")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
