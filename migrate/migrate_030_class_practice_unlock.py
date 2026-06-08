"""Add class_practice_unlock table for topic-level practice visibility."""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE

def run():
    conn = sqlite3.connect(DATABASE)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS class_practice_unlock (
                klasse_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                PRIMARY KEY (klasse_id, task_id)
            )
        ''')
        conn.commit()
        print("Created class_practice_unlock table.")
    finally:
        conn.close()

if __name__ == '__main__':
    run()
