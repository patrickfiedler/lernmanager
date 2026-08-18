"""Add klasse.klassenstufe.

Lernmanager tracked a class's grade level nowhere except the free-text
Klasse name (e.g. "6a") -- fine for display, but not something the
student_mapping.csv roster check (admin/bewertung/netzwerk-ids) can compare
against safely. This adds an explicit, admin-editable field instead of
parsing it out of the name.

Ref: Lernmanager/todo.md § Netzwerk-ID / roster CSV cross-check.
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

        if 'klassenstufe' not in columns:
            conn.execute("ALTER TABLE klasse ADD COLUMN klassenstufe INTEGER DEFAULT NULL")
            print("Added 'klassenstufe' column to klasse table.")
        else:
            print("Column 'klassenstufe' already exists on klasse, skipping.")

        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
