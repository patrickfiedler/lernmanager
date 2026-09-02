"""Move material files out of the flat upload namespace into per-topic folders.

Until now every ZIP-imported material landed at `instance/uploads/<filename>`,
keyed by filename alone, and the import step overwrote whatever was already
there. Two topics could therefore not ship a file under the same name: whichever
was imported second silently clobbered the other's file, and both cohorts then
downloaded the wrong content.

That matters most for a Seilbahn twin, which is supposed to be invisible in the
classroom -- same task title, same keyword, near-identical content -- so that a
Seilbahn student's screen does not mark them out to a neighbour. Forcing the twin
to rename its file undoes that: two materials lists side by side give the track
away by filename alone.

After this migration a file's pfad is `<folder>/<filename>`, where folder is the
topic's `unit_slug` (readable on the server, DB-UNIQUE, restricted to
^[a-z0-9_]+$) or `thema-<id>` when it has none. The two can never collide: that
regex forbids the dash. Nothing outside the DB relies on the flat layout -- the
exchange format keeps bare filenames, and both nginx (alias) and Flask
(send_from_directory) serve a subfolder unchanged.

A file two topics currently share is COPIED into each topic's folder, not moved.
Sharing was an accident of the flat namespace, never a decision, and it is the
exact coupling this change exists to break: after the copy, re-importing one
topic can no longer change the other's material.

The original file is left in place. It costs a few hundred kB and it is the only
undo available if a path turns out wrong -- deleting it is a separate decision,
not this migration's to make.
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE, UPLOAD_FOLDER
from utils import material_pfad


def run():
    if not os.path.exists(DATABASE):
        print(f"Database not found: {DATABASE}")
        return

    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if 'material' not in tables:
            print("Table 'material' does not exist, skipping.")
            return

        rows = conn.execute("""
            SELECT m.id, m.pfad, m.task_id, t.unit_slug
            FROM material m JOIN task t ON t.id = m.task_id
            WHERE m.typ = 'datei'
        """).fetchall()

        # Counted up front: once a row is repointed the shared name looks unique,
        # so asking mid-loop would report the second copy of a pair as a move.
        flat = [r['pfad'] for r in rows if r['pfad'] and '/' not in r['pfad']]
        shared_names = {p for p in flat if flat.count(p) > 1}

        moved = copied = already = missing = skipped = 0
        for row in rows:
            old_pfad = row['pfad'] or ''
            if '/' in old_pfad:
                already += 1
                continue  # a previous run of this migration

            new_pfad = material_pfad(row['task_id'], old_pfad, row['unit_slug'])
            if not new_pfad:
                print(f"  ! material {row['id']}: unusable pfad {old_pfad!r}, left alone")
                skipped += 1
                continue

            src = os.path.join(UPLOAD_FOLDER, old_pfad)
            dest = os.path.join(UPLOAD_FOLDER, new_pfad)

            if os.path.isfile(dest):
                already += 1  # a previous run, or a second row pointing at the same file
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
                if old_pfad in shared_names:
                    copied += 1  # breaks the coupling between two topics
                else:
                    moved += 1
            else:
                # The row is still repointed: the file is missing either way, and
                # a consistent pfad is what a later re-import needs to land right.
                print(f"  ! file missing on disk: {old_pfad} (material {row['id']}), pfad updated anyway")
                missing += 1

            conn.execute("UPDATE material SET pfad = ? WHERE id = ?", (new_pfad, row['id']))

        conn.commit()
        print(f"\nDone. {moved} file(s) filed under their topic, "
              f"{copied} copied out of a shared name, {already} already in place, "
              f"{missing} missing on disk, {skipped} skipped.")
        print("Originals left in place under instance/uploads/ as an undo path.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run()
