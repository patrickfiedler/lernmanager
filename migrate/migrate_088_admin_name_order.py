"""How student names are sorted and shown, per teacher account.

Patrick, 2026-11-25: some lists read better as "Vorname Nachname". The choice is
kept in the account (school PCs wipe browser storage), default unchanged.

    admin.name_order   'nachname' (Nachname, Vorname) | 'vorname' (Vorname Nachname)
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
        if 'name_order' in cols:
            print("  admin.name_order already exists, skipping.")
        else:
            conn.execute("ALTER TABLE admin ADD COLUMN name_order TEXT NOT NULL DEFAULT 'nachname'")
            print("  Added admin.name_order.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
