"""Add quiz_snapshot_json column to quiz_attempt.

Stores the full quiz JSON at the time of the attempt, enabling accurate
question lookup in statistics even if the quiz is later edited.
Old rows get NULL (fall back to current quiz_json in stats).
"""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

conn = sqlite3.connect(config.DATABASE)
try:
    conn.execute("ALTER TABLE quiz_attempt ADD COLUMN quiz_snapshot_json TEXT")
    conn.commit()
    print("Added quiz_snapshot_json to quiz_attempt.")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e):
        print("Column already exists, skipping.")
    else:
        raise
finally:
    conn.close()
