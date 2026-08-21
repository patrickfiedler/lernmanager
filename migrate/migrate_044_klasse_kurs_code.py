"""Add klasse.kurs_code.

student_mapping.csv's "Kurs" column (e.g. "GHU 5") is the school's stable
code for a combined class group (3 courses per grade 5/6, 2 starting grade
7) -- Lernmanager only stored the spelled-out class name, so there was no
exact key to match a CSV group to its class year over year. This adds that
key so the roster-sync feature (admin/bewertung/netzwerk-ids) can link a
CSV group once and match it exactly on every future upload.

Ref: Lernmanager/todo.md § Roster sync from student_mapping.csv.
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
        columns = [row[1] for row in conn.execute("PRAGMA table_info(klasse)").fetchall()]

        if 'kurs_code' not in columns:
            conn.execute("ALTER TABLE klasse ADD COLUMN kurs_code TEXT DEFAULT NULL")
            print("Added 'kurs_code' column to klasse table.")
        else:
            print("Column 'kurs_code' already exists on klasse, skipping.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
