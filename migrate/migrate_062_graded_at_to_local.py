"""Convert grading_run.graded_at from the grading service's UTC to local time.

migrate_050 moved the app onto one local clock but skipped every grading_* column
as "all datetime.now()". graded_at is the exception: it is copied from the grading
service's results callback, which sends UTC with an offset ("...+00:00"). The run
page showed it next to the local imported_at, so a run looked graded before it was
imported (reported 2026-09-19). models.import_grading_callback now converts on
arrival via models.to_local(); this fixes the rows already stored.

Idempotent without a marker: only values that still carry an offset are touched,
and the converted ones no longer do.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE
from models import to_local


def has_offset(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except (AttributeError, ValueError):
        return False


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        rows = conn.execute(
            "SELECT id, graded_at FROM grading_run WHERE graded_at IS NOT NULL"
        ).fetchall()
        converted = 0
        for run_id, graded_at in rows:
            if not has_offset(graded_at):
                continue
            conn.execute("UPDATE grading_run SET graded_at = ? WHERE id = ?",
                         (to_local(graded_at), run_id))
            converted += 1
        conn.commit()
        print(f"\nDone. {converted} of {len(rows)} graded_at value(s) converted.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
