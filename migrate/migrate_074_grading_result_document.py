"""The graded document of a result: download copy + WebP preview pages.

Patrick, 2026-11-03: the review page shows the document the grading service
graded best, not only the text the KI read. Files are copied at import time
into instance/uploads/grading/<run>/<login>/dokument/ and go with the media
purge; this column says what was copied.

    grading_result.document_json   {file, size, slimmed, skipped, pages[], pages_total, preview_error}
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
        if 'document_json' in cols:
            print("  grading_result.document_json already exists, skipping.")
        else:
            conn.execute("ALTER TABLE grading_result ADD COLUMN document_json TEXT")
            print("  Added grading_result.document_json.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
