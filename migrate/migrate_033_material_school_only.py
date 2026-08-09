"""Add school_only column to material table (restrict download to school network)."""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def run():
    conn = sqlite3.connect(DATABASE)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(material)").fetchall()]
        if 'school_only' not in columns:
            conn.execute("ALTER TABLE material ADD COLUMN school_only INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            print("Added 'school_only' column to material table.")
        else:
            print("Column 'school_only' already exists, skipping.")
    finally:
        conn.close()

if __name__ == '__main__':
    run()
