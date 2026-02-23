#!/usr/bin/env python3
"""List student accounts from the local DB for UX testing/walkthroughs.

Usage:
    python list_students.py              # all students
    python list_students.py --active     # students with an active topic
    python list_students.py --no-topic   # students without an active topic
    python list_students.py --done       # students with a completed topic
"""
import sqlite3
import sys
from config import DATABASE


def query(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def list_students(filter_state=None):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    rows = query(conn, """
        SELECT
            s.id,
            s.vorname,
            s.nachname,
            s.benutzername,
            s.passwort,
            s.lernpfad,
            t.name AS topic_name,
            st.abgeschlossen
        FROM student s
        LEFT JOIN student_task st ON st.student_id = s.id
            AND st.id = (
                SELECT id FROM student_task
                WHERE student_id = s.id
                ORDER BY abgeschlossen ASC, id DESC
                LIMIT 1
            )
        LEFT JOIN task t ON t.id = st.task_id
        ORDER BY s.nachname, s.vorname
    """)

    filtered = []
    for r in rows:
        state = "kein Thema"
        if r["topic_name"]:
            state = "fertig" if r["abgeschlossen"] else "aktiv"

        if filter_state == "active" and state != "aktiv":
            continue
        if filter_state == "no-topic" and state != "kein Thema":
            continue
        if filter_state == "done" and state != "fertig":
            continue

        filtered.append((r, state))

    conn.close()

    if not filtered:
        print("(keine Ergebnisse)")
        return

    print(f"{'Name':<24} {'Login':<16} {'Passwort':<12} {'Pfad':<10} {'Status':<10} Thema")
    print("-" * 90)
    for r, state in filtered:
        name = f"{r['nachname']}, {r['vorname']}"
        pfad = r["lernpfad"] or "-"
        topic = r["topic_name"] or "-"
        print(f"{name:<24} {r['benutzername']:<16} {r['passwort']:<12} {pfad:<10} {state:<10} {topic}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    filter_map = {"--active": "active", "--no-topic": "no-topic", "--done": "done"}
    list_students(filter_map.get(arg))
