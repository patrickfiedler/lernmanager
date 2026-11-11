"""Zeilen sammeln (MBI request 2026-11-11, Kl.7 Unit 3 Schulweg-Daten).

One line of text per student, collected by an Aufgabe (`sammeln`), downloaded by
the whole class as .txt (`sammeln_download`). Replaces a shared Etherpad.

    subtask.sammeln_json   JSON {"sammeln": {...}} and/or {"sammeln_download": {...}}
    sammel_zeile           one row per (klasse, sammel_id, student)

Rows key on the class and the collection id, not on the subtask: they survive a
topic re-import, and a Seilbahn twin with the same id fills the same collection.
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()}
        if 'sammeln_json' in cols:
            print("  subtask.sammeln_json already exists, skipping.")
        else:
            conn.execute("ALTER TABLE subtask ADD COLUMN sammeln_json TEXT")
            print("  Added subtask.sammeln_json.")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sammel_zeile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                sammel_id TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                geaendert TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE (klasse_id, sammel_id, student_id),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            )
        """)
        print("  sammel_zeile table ready.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
