#!/usr/bin/env python3
"""Migration: Add llm_usage table for LLM grading rate limiting.

Run BEFORE deploying code changes:
    python migrate_add_llm_usage.py
"""

import os
import sys

# SQLCipher support
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
if SQLCIPHER_KEY:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
    except ImportError:
        import sqlite3
        print("WARNING: SQLCIPHER_KEY set but sqlcipher3 not installed.", file=sys.stderr)
else:
    import sqlite3

import config


def migrate():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    if SQLCIPHER_KEY:
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')
    conn.execute("PRAGMA foreign_keys = ON")

    # Check if table already exists
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_usage'"
    ).fetchone()

    if existing:
        print("Table llm_usage already exists. Nothing to do.")
        conn.close()
        return

    conn.executescript('''
        CREATE TABLE llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            question_type TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
        );

        CREATE INDEX idx_llm_usage_student_time
        ON llm_usage(student_id, timestamp);
    ''')

    conn.commit()
    conn.close()
    print("Created llm_usage table with index.")


if __name__ == '__main__':
    migrate()
