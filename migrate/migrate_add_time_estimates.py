#!/usr/bin/env python3
"""
Database Migration: Add time estimates to subtasks

Adds estimated_minutes field to subtask table for ADHD support (UX Tier 1).
Field is optional (NULL allowed) - shows "~15-30 Min" as fallback if not set.
"""

import os
import sys
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'

def migrate():
    """Add estimated_minutes column to subtask table."""

    # Check if database exists
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        print("  This migration should be run from the project root directory")
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
    print("Migration: Add time estimates to subtasks")
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
        # Verify decryption worked
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            print("✗ Failed to decrypt database with provided key")
            sys.exit(1)

    cursor = conn.cursor()

    # Check if column already exists
    print("\nStep 3: Checking if column already exists...")
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'estimated_minutes' in columns:
        print("✓ Column 'estimated_minutes' already exists - migration already applied")
        print("\nNothing to do. Migration complete.")
        conn.close()
        return

    # Add column
    print("\nStep 4: Adding estimated_minutes column to subtask table...")
    try:
        cursor.execute('''
            ALTER TABLE subtask
            ADD COLUMN estimated_minutes INTEGER NULL
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
    cursor.execute("PRAGMA table_info(subtask)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'estimated_minutes' in columns:
        print("✓ Verification successful")
    else:
        print("✗ Verification failed - column not found")
        conn.close()
        sys.exit(1)

    # Show sample data
    print("\nStep 6: Checking existing subtasks...")
    cursor.execute("SELECT COUNT(*) as count FROM subtask")
    count = cursor.fetchone()[0]
    print(f"✓ Found {count} existing subtasks")
    print(f"  All will have estimated_minutes = NULL (shows '~15-30 Min' fallback in UI)")

    conn.close()

    print("\n" + "=" * 70)
    print("Migration completed successfully!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Admin can now add time estimates when editing tasks")
    print("  2. Students will see time estimates on subtasks that have them")
    print("  3. Existing subtasks show generic '~15-30 Min' until estimates are added")
    print()

if __name__ == '__main__':
    migrate()
