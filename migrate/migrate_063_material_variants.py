"""Material variants: each student of a topic works on one combination from a pool.

MBI request 2026-09-24 (Kl.7 Unit 3, picture forgeries): the topic lists the
allowed combinations, Lernmanager hands each student one and fills {key.N}
placeholders in the task text with the material's label.

    task.material_variants_json   [{key, assignment, sets}] from the import
    material.label                short name that replaces a placeholder
    student_material_variant      the combination a student got (see models.py)
"""
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

# Written out in full: tests/test_schema_parity.py greps for the literal
# "ALTER TABLE <t> ADD COLUMN <c>" text.
NEW_COLUMNS = [
    ('task', 'material_variants_json',
     "ALTER TABLE task ADD COLUMN material_variants_json TEXT"),
    ('material', 'label',
     "ALTER TABLE material ADD COLUMN label TEXT"),
]

NEW_TABLE = """
    CREATE TABLE IF NOT EXISTS student_material_variant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        task_id INTEGER NOT NULL,
        klasse_id INTEGER,
        variant_key TEXT NOT NULL,
        files_json TEXT NOT NULL,
        assigned_at TEXT NOT NULL,
        UNIQUE(student_id, task_id, variant_key),
        FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
        FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
    )
"""


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        added = 0
        for table, column, statement in NEW_COLUMNS:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column in cols:
                print(f"  {table}.{column} already exists, skipping.")
                continue
            conn.execute(statement)
            print(f"  Added {table}.{column}.")
            added += 1
        conn.execute(NEW_TABLE)
        conn.commit()
        print(f"\nDone. {added} column(s) added, student_material_variant ensured.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
