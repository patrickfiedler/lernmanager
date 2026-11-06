"""Material visible only to some classes (MBI request 2026-11-06).

Kl.7 Unit 3: every Lerngruppe collects data in its own Etherpad; with all three
links visible, rows land in the wrong pad. The import names the classes, the
importer stores their ids here.

    material.klasse_ids   JSON list of klasse ids, NULL = visible to every class
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
        cols = {row[1] for row in conn.execute("PRAGMA table_info(material)").fetchall()}
        if 'klasse_ids' in cols:
            print("  material.klasse_ids already exists, skipping.")
        else:
            conn.execute("ALTER TABLE material ADD COLUMN klasse_ids TEXT")
            print("  Added material.klasse_ids.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
