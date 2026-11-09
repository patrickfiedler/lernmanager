"""Class practice unlock may include checkpoint questions (Patrick 2026-11-09).

Chemie 12: the unit was rewritten during the lessons, the class worked on paper
and never sat the checkpoints in Lernmanager -- so practice stayed empty. The
teacher can now unlock a Thema's checkpoint questions for a whole class.

    class_practice_unlock.include_checkpoints   1 = checkpoint questions too
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(class_practice_unlock)").fetchall()}
        if 'include_checkpoints' in cols:
            print("  class_practice_unlock.include_checkpoints already exists, skipping.")
        else:
            conn.execute(
                "ALTER TABLE class_practice_unlock ADD COLUMN include_checkpoints INTEGER NOT NULL DEFAULT 0")
            print("  Added class_practice_unlock.include_checkpoints.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
