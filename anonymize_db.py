#!/usr/bin/env python3
"""
anonymize_db.py — Copy production DB and replace all PII with fake data.

Usage:
    python anonymize_db.py                        # data/mbi_tracker.db → data/mbi_tracker_anon.db
    python anonymize_db.py /path/to/prod.db       # custom source
    python anonymize_db.py prod.db anon.db         # custom source + output
    python anonymize_db.py --overwrite            # overwrite output if it exists
"""

import argparse
import random
import shutil
import sqlite3
import sys
from pathlib import Path

from models import hash_password

# ---------------------------------------------------------------------------
# Fake name pools (seeded per student_id → deterministic across runs)
# ---------------------------------------------------------------------------
FIRST_NAMES = ["Luca", "Emma", "Tim", "Mia", "Felix", "Lena", "Jonas", "Anna",
               "Max", "Laura", "Leon", "Sophie", "Noah", "Lisa", "Ben", "Clara",
               "Paul", "Marie", "Jan", "Julia"]

LAST_NAMES  = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer",
               "Wagner", "Becker", "Hoffmann", "Schäfer", "Koch", "Richter",
               "Bauer", "Klein", "Wolf", "Schröder", "Neumann", "Zimmermann",
               "Braun", "Krüger"]

# Class section replacements: each position cycles through x/y/z/w
SECTION_CYCLE = ["x", "y", "z", "w"]


def fake_name(student_id):
    """Return (vorname, nachname) deterministically seeded by student_id."""
    rng = random.Random(student_id)
    return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)


def anonymize_klasse_name(name, position):
    """Replace section letter in class name, keeping grade. '5a' → '5x'."""
    import re
    section = SECTION_CYCLE[position % len(SECTION_CYCLE)]
    # Replace trailing letter(s) that form the section
    return re.sub(r'[A-Za-z]+$', section, name)


def main():
    parser = argparse.ArgumentParser(description="Anonymize a Lernmanager SQLite DB.")
    parser.add_argument("source", nargs="?", default="data/mbi_tracker.db")
    parser.add_argument("output", nargs="?", default="data/mbi_tracker_anon.db")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite output file if it already exists.")
    args = parser.parse_args()

    src = Path(args.source)
    out = Path(args.output)

    if not src.exists():
        sys.exit(f"Error: source DB not found: {src}")

    if out.exists():
        if args.overwrite:
            out.unlink()
        else:
            sys.exit(f"Error: output already exists: {out}  (use --overwrite to force)")

    # --- Copy DB (never touch source) ---
    shutil.copy2(src, out)
    print(f"Copied {src} → {out}")

    # --- Pre-compute hashes once ---
    student_pw_hash = hash_password("test1234")
    admin_pw_hash   = hash_password("admin1234")

    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row

    with con:
        # 1. Students: replace names + password
        students = con.execute("SELECT id FROM student").fetchall()
        for row in students:
            vorname, nachname = fake_name(row["id"])
            con.execute(
                "UPDATE student SET vorname=?, nachname=?, password_hash=? WHERE id=?",
                (vorname, nachname, student_pw_hash, row["id"])
            )
        print(f"  {len(students)} students renamed, passwords set to 'test1234'")

        # 2. Admins: reset username + password
        admins = con.execute("SELECT id FROM admin").fetchall()
        for i, row in enumerate(admins):
            username = "admin" if i == 0 else f"admin{i+1}"
            con.execute(
                "UPDATE admin SET username=?, password_hash=? WHERE id=?",
                (username, admin_pw_hash, row["id"])
            )
        print(f"  {len(admins)} admin(s) reset (username='admin', password='admin1234')")

        # 3. Classes: replace section letter, keep grade number
        klassen = con.execute("SELECT id, name FROM klasse ORDER BY id").fetchall()
        for i, row in enumerate(klassen):
            new_name = anonymize_klasse_name(row["name"], i)
            con.execute("UPDATE klasse SET name=? WHERE id=?", (new_name, row["id"]))
        print(f"  {len(klassen)} class name(s) anonymized")

        # 4. Lesson comments → NULL
        r = con.execute("UPDATE unterricht SET kommentar=NULL WHERE kommentar IS NOT NULL")
        print(f"  {r.rowcount} unterricht comment(s) cleared")

        # 5. Per-student lesson comments → NULL (table may not exist on all installs)
        try:
            r = con.execute(
                "UPDATE unterricht_student SET admin_kommentar=NULL "
                "WHERE admin_kommentar IS NOT NULL"
            )
            print(f"  {r.rowcount} unterricht_student comment(s) cleared")
        except sqlite3.OperationalError:
            pass  # table doesn't exist in this DB version

        # 6. Delete saved reports (PDF files won't exist locally)
        try:
            r = con.execute("DELETE FROM saved_reports")
            print(f"  {r.rowcount} saved report row(s) deleted")
        except sqlite3.OperationalError:
            pass

        # 7. Delete error log
        try:
            r = con.execute("DELETE FROM error_log")
            print(f"  {r.rowcount} error log row(s) deleted")
        except sqlite3.OperationalError:
            pass

    con.close()
    print(f"\nDone. Anonymized DB: {out}")
    print("  Student login: <username> / test1234")
    print("  Admin login:   admin / admin1234")


if __name__ == "__main__":
    main()
