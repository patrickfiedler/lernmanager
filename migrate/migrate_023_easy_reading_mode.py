#!/usr/bin/env python3
"""
Database Migration: Add easy reading mode preference

Adds easy_reading_mode boolean field to student table for dyslexia support (UX Tier 1).
"""

import os
import sys
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'

def migrate():
    """Add easy_reading_mode column to student table."""

    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        sys.exit(1)

    # Check if we're using SQLCipher
    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    if sqlcipher_key:
        print("✓ Using SQLCipher (encrypted database)")
        try:
            from sqlcipher3 import dbapi2 as sqlite3
        except ImportError:
            print("✗ sqlcipher3 not installed")
            print("  Install with: pip install sqlcipher3-binary")
            sys.exit(1)
    else:
        print("✓ Using standard SQLite (unencrypted database)")
        import sqlite3

    print()
    print("=" * 70)
    print("Migration: Add easy reading mode preference")
    print("=" * 70)

    # Create backup
    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    # Connect to database
    print("\nStep 2: Connecting to database...")
    conn = sqlite3.connect(DB_PATH)
    if sqlcipher_key:
        conn.execute(f"PRAGMA key = '{sqlcipher_key}'")
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            print("✗ Failed to decrypt database with provided key")
            sys.exit(1)

    cursor = conn.cursor()

    # Check if column already exists
    print("\nStep 3: Checking if column already exists...")
    cursor.execute("PRAGMA table_info(student)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'easy_reading_mode' in columns:
        print("✓ Column 'easy_reading_mode' already exists - migration already applied")
        conn.close()
        return

    # Add column
    print("\nStep 4: Adding easy_reading_mode column to student table...")
    try:
        cursor.execute('''
            ALTER TABLE student
            ADD COLUMN easy_reading_mode INTEGER DEFAULT 0
        ''')
        conn.commit()
        print("✓ Column added successfully")
    except sqlite3.Error as e:
        print(f"✗ Error adding column: {e}")
        conn.rollback()
        conn.close()
        sys.exit(1)

    # Verify
    print("\nStep 5: Verifying migration...")
    cursor.execute("PRAGMA table_info(student)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'easy_reading_mode' in columns:
        print("✓ Verification successful")
    else:
        print("✗ Verification failed")
        conn.close()
        sys.exit(1)

    conn.close()

    print("\n" + "=" * 70)
    print("Migration completed successfully!")
    print("=" * 70)

if __name__ == '__main__':
    migrate()
