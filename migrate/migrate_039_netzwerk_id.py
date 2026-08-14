"""Add student.netzwerk_id and backfill it for existing students.

grading-service-deployment.md §Phase 2: matching a scan-folders submission
folder (surname.firstname/) to an enrolled student needs a stable key.
Without this, the importer would need fuzzy nachname/vorname matching -
fragile against umlaut spelling, double surnames, etc. netzwerk_id is
generated with the same lastname.firstname/12-char algorithm as
grading-with-llm's scripts/generate_student_ids.py (ported into
models.generate_netzwerk_id so app.py's batch-add route can assign it to new
students going forward too - see admin_klasse_schueler_hinzufuegen).

Ref: Lernmanager/todo.md § Graded Artifacts.
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE
import models


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(student)").fetchall()]

        if 'netzwerk_id' not in columns:
            conn.execute("ALTER TABLE student ADD COLUMN netzwerk_id TEXT")
            print("Added 'netzwerk_id' column to student table.")
        else:
            print("Column 'netzwerk_id' already exists on student, skipping.")

        existing_index = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_student_netzwerk_id'"
        ).fetchone()[0]
        if existing_index:
            print("Unique index 'idx_student_netzwerk_id' already exists, skipping.")
        else:
            conn.execute("""
                CREATE UNIQUE INDEX idx_student_netzwerk_id
                ON student(netzwerk_id)
                WHERE netzwerk_id IS NOT NULL
            """)
            print("Added partial unique index 'idx_student_netzwerk_id' (NULLs allowed, non-NULL must be unique).")

        conn.commit()

        rows = conn.execute("SELECT id, nachname, vorname, netzwerk_id FROM student ORDER BY id").fetchall()
        existing_ids = {r['netzwerk_id'] for r in rows if r['netzwerk_id']}
        assigned = 0
        for row in rows:
            if row['netzwerk_id']:
                continue
            netzwerk_id = models.generate_netzwerk_id(row['nachname'], row['vorname'], existing_ids)
            existing_ids.add(netzwerk_id)
            conn.execute("UPDATE student SET netzwerk_id = ? WHERE id = ?", (netzwerk_id, row['id']))
            assigned += 1
            print(f"  {row['nachname']}, {row['vorname']} -> {netzwerk_id}")
        conn.commit()
        print(f"Backfilled netzwerk_id for {assigned} student(s) ({len(rows) - assigned} already had one).")
    finally:
        conn.close()


if __name__ == '__main__':
    run()
