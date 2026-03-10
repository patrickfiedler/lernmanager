#!/usr/bin/env python3
"""
Migration script to remove the password_plain column from the student table.

This improves security by not storing plaintext passwords.
Passwords are now only visible:
- In the PDF when batch-creating students
- In the flash message when resetting a password

Usage:
    python migrate_drop_password_plain.py

For encrypted databases:
    SQLCIPHER_KEY=your_key python migrate_drop_password_plain.py
"""

import os
import sys

# Set up path to import from project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

# Handle SQLCipher if configured
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
if SQLCIPHER_KEY:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
        USE_SQLCIPHER = True
    except ImportError:
        import sqlite3
        USE_SQLCIPHER = False
        print("WARNING: SQLCIPHER_KEY set but sqlcipher3 not installed.", file=sys.stderr)
else:
    import sqlite3
    USE_SQLCIPHER = False


def get_connection():
    """Get database connection with optional encryption."""
    conn = sqlite3.connect(config.DATABASE)
    if USE_SQLCIPHER and SQLCIPHER_KEY:
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')
    return conn


def check_column_exists(conn):
    """Check if password_plain column exists."""
    cursor = conn.execute("PRAGMA table_info(student)")
    columns = [row[1] for row in cursor.fetchall()]
    return 'password_plain' in columns


def migrate():
    """Remove password_plain column from student table."""
    if not os.path.exists(config.DATABASE):
        print(f"Database not found: {config.DATABASE}")
        print("Nothing to migrate.")
        return

    conn = get_connection()

    if not check_column_exists(conn):
        print("Column 'password_plain' does not exist. Migration already complete.")
        conn.close()
        return

    print(f"Migrating database: {config.DATABASE}")
    print("Removing password_plain column from student table...")

    # SQLite 3.35.0+ supports ALTER TABLE DROP COLUMN
    # For older versions, we need to recreate the table
    sqlite_version = sqlite3.sqlite_version_info

    if sqlite_version >= (3, 35, 0):
        # Modern SQLite - use DROP COLUMN
        print(f"SQLite version {sqlite3.sqlite_version} supports DROP COLUMN")
        conn.execute("ALTER TABLE student DROP COLUMN password_plain")
        conn.commit()
    else:
        # Older SQLite - recreate table
        print(f"SQLite version {sqlite3.sqlite_version} - using table recreation method")

        conn.execute("BEGIN TRANSACTION")
        try:
            # Create new table without password_plain
            conn.execute("""
                CREATE TABLE student_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nachname TEXT NOT NULL,
                    vorname TEXT NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )
            """)

            # Copy data
            conn.execute("""
                INSERT INTO student_new (id, nachname, vorname, username, password_hash)
                SELECT id, nachname, vorname, username, password_hash FROM student
            """)

            # Drop old table and rename new one
            conn.execute("DROP TABLE student")
            conn.execute("ALTER TABLE student_new RENAME TO student")

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

    conn.close()
    print("Migration complete! password_plain column has been removed.")


if __name__ == '__main__':
    migrate()
