"""Add attribution column to material table (photographer/source credit)."""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def run():
    conn = sqlite3.connect(DATABASE)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(material)").fetchall()]
        if 'attribution' not in columns:
            conn.execute("ALTER TABLE material ADD COLUMN attribution TEXT")
            conn.commit()
            print("Added 'attribution' column to material table.")
        else:
            print("Column 'attribution' already exists, skipping.")
    finally:
        conn.close()

if __name__ == '__main__':
    run()
