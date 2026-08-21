"""Add is_intro column to subtask table (excludes intro/Einführung subtasks from the progress-count denominator)."""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def run():
    conn = sqlite3.connect(DATABASE)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtask)").fetchall()]
        if 'is_intro' not in columns:
            conn.execute("ALTER TABLE subtask ADD COLUMN is_intro INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            print("Added 'is_intro' column to subtask table.")
        else:
            print("Column 'is_intro' already exists, skipping.")
    finally:
        conn.close()

if __name__ == '__main__':
    run()
