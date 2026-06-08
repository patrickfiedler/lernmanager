"""Add practice_unlocked flag to student_task."""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def run():
    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute("ALTER TABLE student_task ADD COLUMN practice_unlocked INTEGER DEFAULT 0")
        conn.commit()
        print("Added practice_unlocked column to student_task.")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e):
            print("Column already exists, skipping.")
        else:
            raise
    finally:
        conn.close()

if __name__ == '__main__':
    run()
