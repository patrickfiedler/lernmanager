"""Zeilen sammeln: a collection belongs to its Thema, not only to the class (Patrick 2026-11-13).

    sammel_zeile.thema       the Thema's key (models.sammel_thema): the regular
                             topic's unit_slug for a Seilbahn twin, else its own
                             unit_slug, else 'task-<id>'. Part of the unique key,
                             so two Themen using the same `id` no longer share lines.
    sammel_zeile_log.thema   same, for the audit trail

SQLite cannot change a UNIQUE constraint, so sammel_zeile is rebuilt.
Existing rows get their Thema from the one topic whose subtask collects that id;
an id used by several topics (or none) stays '' and is printed for a hand fix.
"""
import json
import shutil
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE


def _thema_by_sammel_id(conn):
    """sammel_id -> set of Thema keys of the topics that collect it."""
    found = {}
    rows = conn.execute("""
        SELECT s.sammeln_json, t.id, t.unit_slug, t.seilbahn_of
        FROM subtask s JOIN task t ON t.id = s.task_id
        WHERE s.sammeln_json IS NOT NULL
    """).fetchall()
    for sammeln_json, task_id, unit_slug, seilbahn_of in rows:
        cfg = (json.loads(sammeln_json) or {}).get('sammeln')
        if cfg and cfg.get('id'):
            found.setdefault(cfg['id'], set()).add(seilbahn_of or unit_slug or f'task-{task_id}')
    return found


def run():
    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sammel_zeile)").fetchall()}
        if 'thema' in cols:
            print("  sammel_zeile.thema already exists, skipping.")
            return
        conn.execute("""
            CREATE TABLE sammel_zeile_neu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                thema TEXT NOT NULL DEFAULT '',
                sammel_id TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                geaendert TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                text_frei TEXT,
                abgelehnt INTEGER NOT NULL DEFAULT 0,
                UNIQUE (klasse_id, thema, sammel_id, student_id),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            INSERT INTO sammel_zeile_neu (id, klasse_id, sammel_id, student_id, text, geaendert, text_frei, abgelehnt)
            SELECT id, klasse_id, sammel_id, student_id, text, geaendert, text_frei, abgelehnt FROM sammel_zeile
        """)
        conn.execute("DROP TABLE sammel_zeile")
        conn.execute("ALTER TABLE sammel_zeile_neu RENAME TO sammel_zeile")
        conn.execute("ALTER TABLE sammel_zeile_log ADD COLUMN thema TEXT NOT NULL DEFAULT ''")

        for sammel_id, themen in _thema_by_sammel_id(conn).items():
            if len(themen) == 1:
                thema = next(iter(themen))
                for table in ('sammel_zeile', 'sammel_zeile_log'):
                    conn.execute(f"UPDATE {table} SET thema = ? WHERE sammel_id = ? AND thema = ''",
                                 (thema, sammel_id))
        left = conn.execute("SELECT DISTINCT sammel_id FROM sammel_zeile WHERE thema = ''").fetchall()
        for (sammel_id,) in left:
            print(f"  ! Lines of '{sammel_id}' have no Thema (id used by several topics or none): fix by hand.")
        print("  sammel_zeile rebuilt with thema; log extended.")
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    run()
