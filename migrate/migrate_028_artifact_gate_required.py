"""Add artifact_gate_required column to klasse.

Controls whether the deterministic artifact gate blocks task completion (1)
or is informational only — students can still self-report (0).
Default 1 preserves existing behaviour for all current classes.
"""
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

conn = sqlite3.connect(config.DATABASE)
try:
    conn.execute("ALTER TABLE klasse ADD COLUMN artifact_gate_required INTEGER NOT NULL DEFAULT 1")
    conn.commit()
    print("Added artifact_gate_required to klasse.")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e):
        print("Column already exists, skipping.")
    else:
        raise
finally:
    conn.close()
