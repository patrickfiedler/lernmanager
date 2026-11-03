"""Which view the review page opens with, per teacher account.

Patrick, 2026-11-03: the review page shows "Was die KI gelesen hat", the
document preview, or both; the choice is kept in the account, because school
PCs wipe browser storage on logout.

    admin.grading_view   'ki' | 'vorschau' | 'beides', default 'ki'
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(admin)").fetchall()}
        if 'grading_view' in cols:
            print("  admin.grading_view already exists, skipping.")
        else:
            conn.execute("ALTER TABLE admin ADD COLUMN grading_view TEXT NOT NULL DEFAULT 'ki'")
            print("  Added admin.grading_view.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
