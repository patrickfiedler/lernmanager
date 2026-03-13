"""Migration 010: Add completed_at to student_subtask for spaced repetition recency signal."""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def migrate():
    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute('ALTER TABLE student_subtask ADD COLUMN completed_at DATETIME')
        conn.commit()
        print("Added completed_at to student_subtask (existing rows = NULL = treated as old material).")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e):
            print("Column already exists, skipping.")
        else:
            raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
