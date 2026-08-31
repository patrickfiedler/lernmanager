"""Switch the work-step checkboxes on for everyone.

migrate_053 shipped them opt-in (default 0) on the reasoning that the steps
are already numbered and spaced, so checkboxes are for students who lose
their place. Patrick's call after seeing them on real content, 2026-08-31:
make them the default. Students who don't want them switch them off in
Einstellungen.

Two halves, because SQLite cannot ALTER a column default without rebuilding
the table -- not worth the risk on a live student table with cascading
foreign keys:
  * existing rows -> 1, here;
  * new students -> models.create_student() passes 1 explicitly.
The column DEFAULT stays 0 so init_db() and production keep matching; the
real default lives in create_student().

Safe to run as written: nothing is deployed yet, so no student has chosen to
switch this off and there is no preference to overwrite. If this ever needs
running again, it would need to spare rows a student had set to 0 -- there is
no way to tell those apart from the untouched ones.
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(student)").fetchall()}
        if 'step_checkboxes' not in cols:
            print("Column student.step_checkboxes missing, run migrate_053 first.")
            return

        cursor = conn.execute("UPDATE student SET step_checkboxes = 1 WHERE step_checkboxes = 0")
        conn.commit()
        print(f"\nDone. {cursor.rowcount} student(s) switched on.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
