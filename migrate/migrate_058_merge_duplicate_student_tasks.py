"""Fold duplicate student_task rows back into one, keeping every checkmark.

Until the guard in assign_task_to_student was repaired, reassigning a topic a
student had already finished inserted a *second* student_task row instead of
recognising the first. The guard completed every active primary in step 1 and
then looked for an active row in step 2, so for rolle='primary' it could never
find one and always inserted.

The damage is not ambiguity -- step 1 kept exactly one row active -- but lost
progress. student_subtask and quiz_attempt hang off student_task.id, not off
(student_id, subtask_id), so the new row starts empty: the student is shown a
topic they have already completed, at 0 %, with every checkmark stranded on the
old row.

This migration merges each group of duplicate (student, klasse, topic, rolle)
rows into the one carrying the most work, repointing the children rather than
deleting them. Deleting the newer row would have been simpler, but 17 of the 30
affected rows in production already had a redone Aufgabe and its quiz attempts
on them, and a quiz attempt is a graded record.

The merged row keeps abgeschlossen = 1 where any row in the group was finished:
the student really did complete the topic. That leaves them with no active topic
in that class, which is a state the UI now names on both sides -- the dashboard
says the queue is worked through, and admin/schueler_detail offers the next
queued topic -- rather than the blank page it used to be.

Idempotent: after a successful run no group has more than one row, so a second
run finds nothing. Run with --dry-run to print the plan without writing.
"""
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE


def _groups(conn):
    """Duplicate groups, each already ordered best-keep-candidate first."""
    rows = conn.execute("""
        SELECT st.id, st.student_id, st.klasse_id, st.task_id, st.rolle,
               st.abgeschlossen, st.manuell_abgeschlossen,
               (SELECT COUNT(*) FROM student_subtask ss
                 WHERE ss.student_task_id = st.id AND ss.erledigt = 1) AS done,
               (SELECT COUNT(*) FROM quiz_attempt qa
                 WHERE qa.student_task_id = st.id) AS attempts
          FROM student_task st
    """).fetchall()

    grouped = defaultdict(list)
    for r in rows:
        grouped[(r['student_id'], r['klasse_id'], r['task_id'], r['rolle'])].append(dict(r))

    out = {}
    for key, members in grouped.items():
        if len(members) < 2:
            continue
        # Most completed Aufgaben wins, then most quiz attempts, then the
        # oldest row -- the one the student started on.
        members.sort(key=lambda m: (-m['done'], -m['attempts'], m['id']))
        out[key] = members
    return out


def _merge_student_subtasks(conn, keep_id, drop_id):
    """Repoint, or fold in where the keeper already has that Aufgabe.

    UNIQUE(student_task_id, subtask_id) forbids a blind repoint, and a blind
    delete would drop a tick the keeper does not have.
    """
    kept = {r['subtask_id']: dict(r) for r in conn.execute(
        "SELECT * FROM student_subtask WHERE student_task_id = ?", (keep_id,)).fetchall()}

    for row in conn.execute(
            "SELECT * FROM student_subtask WHERE student_task_id = ?", (drop_id,)).fetchall():
        target = kept.get(row['subtask_id'])
        if target is None:
            conn.execute("UPDATE student_subtask SET student_task_id = ? WHERE id = ?",
                         (keep_id, row['id']))
            kept[row['subtask_id']] = dict(row)
            continue
        conn.execute(
            "UPDATE student_subtask SET erledigt = ?, artifact_gate_passed = ?, completed_at = ? "
            "WHERE id = ?",
            (1 if (target['erledigt'] or row['erledigt']) else 0,
             1 if (target['artifact_gate_passed'] or row['artifact_gate_passed']) else 0,
             min([t for t in (target['completed_at'], row['completed_at']) if t], default=None),
             target['id']))
        conn.execute("DELETE FROM student_subtask WHERE id = ?", (row['id'],))


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)).fetchone() is not None


def _merge_game_progress(conn, keep_id, drop_id):
    """UNIQUE(student_id, student_task_id, question_index): a question the
    keeper already answered wins, the duplicate's row goes.

    game_task_progress is created by a migration, not by init_db(), so a
    database that has not seen that migration does not have the table."""
    if not _table_exists(conn, 'game_task_progress'):
        return
    taken = {r['question_index'] for r in conn.execute(
        "SELECT question_index FROM game_task_progress WHERE student_task_id = ?",
        (keep_id,)).fetchall()}
    for row in conn.execute(
            "SELECT id, question_index FROM game_task_progress WHERE student_task_id = ?",
            (drop_id,)).fetchall():
        if row['question_index'] in taken:
            conn.execute("DELETE FROM game_task_progress WHERE id = ?", (row['id'],))
        else:
            conn.execute("UPDATE game_task_progress SET student_task_id = ? WHERE id = ?",
                         (keep_id, row['id']))
            taken.add(row['question_index'])


def run(dry_run=False):
    if not os.path.exists(DATABASE):
        print(f"Database not found: {DATABASE}")
        return

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    groups = _groups(conn)

    if not groups:
        print("No duplicate student_task rows. Nothing to do.")
        conn.close()
        return

    print(f"{len(groups)} duplicate group(s) found "
          f"({sum(len(m) - 1 for m in groups.values())} row(s) to fold in).\n")
    for (student_id, klasse_id, task_id, rolle), members in sorted(groups.items()):
        keep, drops = members[0], members[1:]
        finished = any(m['abgeschlossen'] for m in members)
        print(f"  student {student_id} / klasse {klasse_id} / thema {task_id} ({rolle}): "
              f"keep #{keep['id']} (done={keep['done']}, attempts={keep['attempts']}) "
              f"<- {', '.join('#%d (done=%d, attempts=%d)' % (d['id'], d['done'], d['attempts']) for d in drops)}"
              f" => abgeschlossen={1 if finished else 0}")

    if dry_run:
        print("\n--dry-run: nothing written.")
        conn.close()
        return

    backup_path = f"{DATABASE}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DATABASE, backup_path)
    print(f"\nBackup created: {backup_path}")

    try:
        merged = 0
        for members in groups.values():
            keep, drops = members[0], members[1:]
            for drop in drops:
                _merge_student_subtasks(conn, keep['id'], drop['id'])
                _merge_game_progress(conn, keep['id'], drop['id'])
                conn.execute("UPDATE quiz_attempt SET student_task_id = ? WHERE student_task_id = ?",
                             (keep['id'], drop['id']))
                conn.execute("DELETE FROM student_task WHERE id = ?", (drop['id'],))
                merged += 1
            conn.execute(
                "UPDATE student_task SET abgeschlossen = ?, manuell_abgeschlossen = ? WHERE id = ?",
                (1 if any(m['abgeschlossen'] for m in members) else 0,
                 1 if any(m['manuell_abgeschlossen'] for m in members) else 0,
                 keep['id']))
        conn.commit()
        print(f"Done. {merged} duplicate row(s) folded into {len(groups)} kept row(s).")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    run(dry_run='--dry-run' in sys.argv)
