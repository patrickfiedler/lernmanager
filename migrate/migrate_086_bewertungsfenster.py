"""Bewertungsfenster: the period a grade is computed over (chemie, 2026-09-01).

A window belongs to one class and names the modules (topics) expected in it. The
denominator of every grade is derived from that list, never typed in. Every change
to a window is logged, because a changed module list silently moves everyone's
denominator. Frozen from the day after the Stichtag, or earlier by hand
(eingefroren_am, models.fenster_ist_eingefroren).

Plan: task_plan.md § Chemies Notenrechnung, Phase 1. Additive only.
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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bewertungsfenster (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start_datum TEXT NOT NULL,
                stichtag TEXT NOT NULL,
                eingefroren_am TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS bewertungsfenster_modul (
                fenster_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                PRIMARY KEY (fenster_id, task_id),
                FOREIGN KEY (fenster_id) REFERENCES bewertungsfenster(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS bewertungsfenster_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fenster_id INTEGER NOT NULL,
                zeitpunkt TEXT NOT NULL,
                admin_id INTEGER,
                aktion TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (fenster_id) REFERENCES bewertungsfenster(id) ON DELETE CASCADE
            );
        """)
        conn.commit()
        print("bewertungsfenster tables ready.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
