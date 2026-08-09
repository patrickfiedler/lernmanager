"""Manual pre-deploy check: does a real database's schema match what a
fresh init_db() would produce right now?

Not part of the automated test suite (see tests/test_schema_parity.py for
that) - this compares an *actual* database file, which is the most direct
answer to "is this DB missing anything," but isn't something a fresh clone
or CI could run (the file is machine-specific and gitignored). Run by hand
before a deploy if you want to double-check.

Usage:
    ./venv/bin/python migrate/schema_parity_diagnostic.py [path/to/db]

    Defaults to config.DATABASE (the local dev DB). To check a production
    DB, copy it down first (e.g. scp) and pass its path.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import models


def _table_columns(db_path):
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]
    columns = {}
    for t in tables:
        columns[t] = {row[1] for row in conn.execute(f"PRAGMA table_info({t})").fetchall()}
    conn.close()
    return columns


def run(target_path):
    fresh_path = tempfile.mktemp(suffix='.db')
    config.DATABASE = fresh_path
    models.init_db()

    fresh = _table_columns(fresh_path)
    actual = _table_columns(target_path)
    os.remove(fresh_path)

    missing_tables = fresh.keys() - actual.keys()
    extra_tables = actual.keys() - fresh.keys()

    print(f"Comparing {target_path} against a fresh init_db()\n")

    if missing_tables:
        print(f"Tables missing from {target_path}:")
        for t in sorted(missing_tables):
            print(f"  - {t}")
        print()

    if extra_tables:
        print(f"Tables in {target_path} but not in a fresh install (fine if intentional):")
        for t in sorted(extra_tables):
            print(f"  - {t}")
        print()

    any_column_diff = False
    for table in sorted(fresh.keys() & actual.keys()):
        missing_cols = fresh[table] - actual[table]
        extra_cols = actual[table] - fresh[table]
        if missing_cols or extra_cols:
            any_column_diff = True
            print(f"{table}:")
            if missing_cols:
                print(f"  missing: {sorted(missing_cols)}")
            if extra_cols:
                print(f"  extra:   {sorted(extra_cols)}")

    if not missing_tables and not extra_tables and not any_column_diff:
        print("Schema matches a fresh init_db() exactly.")


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else config.DATABASE
    if not os.path.exists(path):
        print(f"Database not found: {path}")
        sys.exit(1)
    run(path)
