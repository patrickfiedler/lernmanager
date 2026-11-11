"""Zeilen sammeln: the teacher approves each line (Patrick 2026-11-11).

    sammel_zeile.text_frei   the approved text; NULL = never approved

Download and copy box hand out only text_frei. A student may add or change
their line at any time (late entries after a missed lesson); the change waits
until the teacher approves it, so the shared data never changes on its own
and nonsense never reaches the class.
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sammel_zeile)").fetchall()}
        if 'text_frei' in cols:
            print("  sammel_zeile.text_frei already exists, skipping.")
        else:
            conn.execute("ALTER TABLE sammel_zeile ADD COLUMN text_frei TEXT")
            print("  Added sammel_zeile.text_frei.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
