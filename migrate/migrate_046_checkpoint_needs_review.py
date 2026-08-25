"""Add needs_review/review_notes columns to checkpoint_attempt (flags a session
where a question's give-up was forced by LLM grading being unavailable, not a
real give-up -- teacher should re-grade by hand)."""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def run():
    conn = sqlite3.connect(DATABASE)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(checkpoint_attempt)").fetchall()]
        if 'needs_review' not in columns:
            conn.execute("ALTER TABLE checkpoint_attempt ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0")
            print("Added 'needs_review' column to checkpoint_attempt table.")
        else:
            print("Column 'needs_review' already exists, skipping.")
        if 'review_notes' not in columns:
            conn.execute("ALTER TABLE checkpoint_attempt ADD COLUMN review_notes TEXT")
            print("Added 'review_notes' column to checkpoint_attempt table.")
        else:
            print("Column 'review_notes' already exists, skipping.")
        conn.commit()
    finally:
        conn.close()

if __name__ == '__main__':
    run()
