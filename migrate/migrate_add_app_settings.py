#!/usr/bin/env python3
"""
Migration script to add app_settings table.

This table stores global application settings as key-value pairs.

Usage:
    # For unencrypted database:
    python migrate_add_app_settings.py [path_to_database]

    # For SQLCipher encrypted database:
    SQLCIPHER_KEY=your_key python migrate_add_app_settings.py [path_to_database]

If no path is provided, uses data/mbi_tracker.db
"""

import sys
import os
from datetime import datetime

# SQLCipher support: Use encrypted database if SQLCIPHER_KEY is set
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
USE_SQLCIPHER = False

if SQLCIPHER_KEY:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
        USE_SQLCIPHER = True
        print("Using SQLCipher encrypted database")
    except ImportError:
        import sqlite3
        print("WARNING: SQLCIPHER_KEY is set but sqlcipher3 is not installed.", file=sys.stderr)
        print("Database will NOT be encrypted. Install with: pip install sqlcipher3-binary", file=sys.stderr)
        sys.exit(1)
else:
    import sqlite3
    print("Using standard SQLite (unencrypted)")


def migrate_database(db_path):
    """Perform the migration."""

    # Backup first
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Creating backup: {backup_path}")

    import shutil
    shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Set encryption key if using SQLCipher
    if USE_SQLCIPHER and SQLCIPHER_KEY:
        # Escape any double quotes in key
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')

    cursor = conn.cursor()

    try:
        print("\n=== Starting Migration ===\n")

        # Check if app_settings table already exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='app_settings'
        """)
        table_exists = cursor.fetchone()

        if table_exists:
            print("✓ app_settings table already exists - migration not needed")
        else:
            print("1. Creating app_settings table...")
            cursor.execute("""
                CREATE TABLE app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("   ✓ Table created")

            print("\n2. Setting default values...")
            # Set default: page view logging enabled
            cursor.execute("""
                INSERT INTO app_settings (key, value)
                VALUES ('log_page_views', 'true')
            """)
            print("   ✓ Default setting: log_page_views = true")

        # Commit changes
        conn.commit()

        print("\n=== Migration Complete ===")
        print(f"\nBackup saved to: {backup_path}")
        print("\nVerification:")

        # Verify table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='app_settings'
        """)
        if cursor.fetchone():
            print("  ✓ app_settings table exists")

        # Show current settings
        cursor.execute("SELECT key, value, updated_at FROM app_settings")
        settings = cursor.fetchall()
        if settings:
            print(f"\nCurrent settings ({len(settings)}):")
            for row in settings:
                print(f"  {row['key']} = {row['value']} (updated: {row['updated_at']})")
        else:
            print("\nNo settings configured yet")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        conn.rollback()
        print(f"Database not modified. Backup is at: {backup_path}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    # Get database path from command line or use default
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Default path relative to script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(script_dir, 'data', 'mbi_tracker.db')

    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    print(f"Migrating database: {db_path}")
    migrate_database(db_path)
    print("\n✓ Migration completed successfully!")
