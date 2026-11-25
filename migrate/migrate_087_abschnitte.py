"""Abschnitte: teacher-graded parts of an Abnahme/Artefakt checkpoint (chemie, docs/32 § 3).

An Artefakt is not graded as a whole: each section gets its own 0/2/3 and counts
like one quiz question (quality grade only). Sections carry a fixed id, same rule
as question ids: reworded = same id, asks something else = new id.

    subtask.abschnitte_json   JSON [{"id": "a1", "text": "..."}]; NULL = graded as one

Plan: task_plan.md § Chemies Notenrechnung, Phase 3. Additive only.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()}
        if 'abschnitte_json' in cols:
            print("  subtask.abschnitte_json already exists, skipping.")
        else:
            conn.execute("ALTER TABLE subtask ADD COLUMN abschnitte_json TEXT")
            print("  Added subtask.abschnitte_json.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
