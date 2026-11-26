"""Grading windows with several modules become one window per module.

Why (Chemie + Patrick, 2026-11-26): every module gets its own grade with its own
Stichtag. A bewertungsfenster row is now "the Stichtag of one module in one class"
(models.get_modul_fenster); the window pages are gone, the Stichtag is set on the
checkpoint overview.

A window with modules A, B keeps A; B gets a copy of the row (name = module name,
same dates and eingefroren_am, so a frozen grade stays frozen). Both get a log row
'aufgeteilt'. Windows without a module are left alone (they count for nothing).

STOPS, writing nothing, when two windows would hold the same module of one class:
which Stichtag is right is a decision, not something to guess. The dry run lists them.

Usage:
    python migrate/migrate_090_fenster_je_modul.py              # config.DATABASE
    python migrate/migrate_090_fenster_je_modul.py --probelauf  # write nothing
    python migrate/migrate_090_fenster_je_modul.py --probelauf path/to/copy.db
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def build_plan(conn):
    """([(window row, [task_id, ...] to split off)], problems). Prints every window."""
    conn.row_factory = sqlite3.Row
    windows = conn.execute("SELECT * FROM bewertungsfenster ORDER BY klasse_id, id").fetchall()
    plan, problems, seen = [], [], {}
    for w in windows:
        modules = conn.execute(
            "SELECT m.task_id, t.name FROM bewertungsfenster_modul m JOIN task t ON t.id = m.task_id "
            "WHERE m.fenster_id = ? ORDER BY t.name", (w['id'],)).fetchall()
        names = ', '.join(m['name'] for m in modules) or 'keine Module'
        print(f"  Klasse {w['klasse_id']}, #{w['id']} „{w['name']}“, Stichtag {w['stichtag']}: {names}")
        for m in modules:
            key = (w['klasse_id'], m['task_id'])
            if key in seen:
                problems.append(f"Klasse {w['klasse_id']}, {m['name']}: in Fenster #{seen[key]} "
                                f"und #{w['id']} -- eines davon löschen")
            seen[key] = w['id']
        if len(modules) > 1:
            plan.append((w, modules[1:]))
    return plan, problems


def apply_plan(conn, plan):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for w, rest in plan:
        for m in rest:
            new_id = conn.execute(
                "INSERT INTO bewertungsfenster (klasse_id, name, start_datum, stichtag, "
                "eingefroren_am, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (w['klasse_id'], m['name'], w['start_datum'], w['stichtag'],
                 w['eingefroren_am'], w['created_at'])).lastrowid
            conn.execute("UPDATE bewertungsfenster_modul SET fenster_id = ? "
                         "WHERE fenster_id = ? AND task_id = ?", (new_id, w['id'], m['task_id']))
            for fid, detail in ((new_id, f"aus „{w['name']}“ (#{w['id']})"),
                                (w['id'], f"{m['name']} -> eigenes Fenster #{new_id}")):
                conn.execute("INSERT INTO bewertungsfenster_log (fenster_id, zeitpunkt, admin_id, "
                             "aktion, detail) VALUES (?, ?, NULL, 'aufgeteilt', ?)",
                             (fid, now, detail))


def run(db_path=None, probelauf=False):
    """Returns True on success. Writes nothing when there is any problem."""
    db_path = db_path or config.DATABASE
    conn = sqlite3.connect(db_path)
    try:
        print(f'{"Probelauf" if probelauf else "Migration"}: {db_path}')
        plan, problems = build_plan(conn)
        if problems:
            print(f'\n{len(problems)} Problem(e), Migration hält an:')
            for p in problems:
                print('  -', p)
            return False
        print(f'{len(plan)} Fenster mit mehreren Modulen.')
        if probelauf or not plan:
            if probelauf:
                print('Probelauf: nichts geschrieben.')
            return True
    finally:
        conn.close()

    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f'Backup created: {backup_path}')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            apply_plan(conn, build_plan(conn)[0])
        print('Fenster aufgeteilt.')
        return True
    finally:
        conn.close()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--probelauf']
    ok = run(args[0] if args else None, probelauf='--probelauf' in sys.argv)
    sys.exit(0 if ok else 1)
