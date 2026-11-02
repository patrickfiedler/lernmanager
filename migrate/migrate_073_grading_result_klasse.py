"""Class a teacher sees a grading result through, set by hand.

Patrick, 2026-11-02: a student who changed classes, or whose file still lay in
the old class's folder, showed a whole foreign run to the new teacher. NULL keeps
the rule in permissions._grading_result_klassen.

    grading_result.klasse_id   set on the run page, admin only
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(grading_result)").fetchall()}
        if 'klasse_id' in cols:
            print("  grading_result.klasse_id already exists, skipping.")
        else:
            conn.execute("ALTER TABLE grading_result ADD COLUMN klasse_id INTEGER")
            print("  Added grading_result.klasse_id.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
