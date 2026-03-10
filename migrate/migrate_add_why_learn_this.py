#!/usr/bin/env python3
"""
Migration: Add why_learn_this column to task table

This migration adds a new TEXT column 'why_learn_this' to the task table
to store brief, age-appropriate explanations of why students need to learn
each topic.

Usage:
    python migrate_add_why_learn_this.py

The script is idempotent - safe to run multiple times.
"""

import os
import sys
from datetime import datetime

# Check for SQLCipher
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
USE_SQLCIPHER = False

if SQLCIPHER_KEY:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
        USE_SQLCIPHER = True
        print(f"✓ Using SQLCipher (encrypted database)")
    except ImportError:
        import sqlite3
        print("WARNING: SQLCIPHER_KEY is set but sqlcipher3 module not found.", file=sys.stderr)
        print("Install with: pip install sqlcipher3-binary", file=sys.stderr)
        sys.exit(1)
else:
    import sqlite3
    print("✓ Using standard SQLite (unencrypted database)")

# Database path
DATABASE = os.path.join(os.path.dirname(__file__), 'data', 'mbi_tracker.db')

def backup_database():
    """Create a backup of the database before migration."""
    if not os.path.exists(DATABASE):
        print(f"ERROR: Database not found at {DATABASE}", file=sys.stderr)
        sys.exit(1)

    backup_path = DATABASE + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    # Copy the file
    import shutil
    shutil.copy2(DATABASE, backup_path)
    print(f"✓ Backup created: {backup_path}")
    return backup_path

def check_column_exists(cursor):
    """Check if why_learn_this column already exists."""
    cursor.execute("PRAGMA table_info(task)")
    columns = [row[1] for row in cursor.fetchall()]
    return 'why_learn_this' in columns

def migrate():
    """Run the migration."""
    print("\n" + "="*60)
    print("Migration: Add why_learn_this to task table")
    print("="*60 + "\n")

    # Step 1: Backup
    print("Step 1: Creating backup...")
    backup_path = backup_database()

    # Step 2: Connect to database
    print("\nStep 2: Connecting to database...")
    conn = sqlite3.connect(DATABASE)

    if USE_SQLCIPHER and SQLCIPHER_KEY:
        # Set encryption key
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')
        print("✓ Encryption key set")

    cursor = conn.cursor()

    # Step 3: Check if column already exists
    print("\nStep 3: Checking if column already exists...")
    if check_column_exists(cursor):
        print("✓ Column 'why_learn_this' already exists - migration already applied")
        print("\nNothing to do. Migration complete.")
        conn.close()
        return

    # Step 4: Add the column
    print("\nStep 4: Adding 'why_learn_this' column...")
    try:
        cursor.execute("""
            ALTER TABLE task
            ADD COLUMN why_learn_this TEXT
        """)
        conn.commit()
        print("✓ Column added successfully")
    except Exception as e:
        print(f"ERROR: Failed to add column: {e}", file=sys.stderr)
        conn.rollback()
        conn.close()
        sys.exit(1)

    # Step 5: Verify
    print("\nStep 5: Verifying migration...")
    if check_column_exists(cursor):
        print("✓ Verification successful - column exists")

        # Show table schema
        cursor.execute("PRAGMA table_info(task)")
        print("\nUpdated task table schema:")
        print("-" * 60)
        for row in cursor.fetchall():
            col_id, name, col_type, not_null, default, pk = row
            nullable = "NOT NULL" if not_null else "NULL"
            pk_marker = " (PRIMARY KEY)" if pk else ""
            default_str = f" DEFAULT {default}" if default else ""
            print(f"  {name:20s} {col_type:10s} {nullable:8s}{default_str}{pk_marker}")
        print("-" * 60)

        # Count existing tasks
        cursor.execute("SELECT COUNT(*) FROM task")
        task_count = cursor.fetchone()[0]
        print(f"\nTotal tasks in database: {task_count}")
        print(f"All tasks now have 'why_learn_this' field (currently NULL/empty)")

    else:
        print("ERROR: Verification failed - column not found", file=sys.stderr)
        conn.close()
        sys.exit(1)

    conn.close()

    print("\n" + "="*60)
    print("✅ Migration completed successfully!")
    print("="*60)
    print(f"\nBackup saved at: {backup_path}")
    print("\nNext steps:")
    print("1. Update admin interface to allow editing 'why_learn_this'")
    print("2. Add purpose statements to existing tasks")
    print("3. Update student view to display the purpose banner")

if __name__ == '__main__':
    try:
        migrate()
    except KeyboardInterrupt:
        print("\n\nMigration cancelled by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: Unexpected error during migration: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
