#!/usr/bin/env python3
"""
Migrate an existing unencrypted SQLite database to SQLCipher encrypted format.

Usage:
    SQLCIPHER_KEY=your_secret_key python migrate_to_sqlcipher.py

This will:
1. Read from data/mbi_tracker.db (unencrypted)
2. Create data/mbi_tracker_encrypted.db (encrypted)
3. Copy all data
4. Optionally replace the original (with backup)

Generate a secure key with:
    python3 -c "import secrets; print(secrets.token_hex(32))"
"""

import os
import sys
import shutil

# Check for encryption key first
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
if not SQLCIPHER_KEY:
    print("ERROR: SQLCIPHER_KEY environment variable is required.")
    print("Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\"")
    sys.exit(1)

# Import after key check
try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:
    print("ERROR: sqlcipher3 not installed.")
    print("Install with: pip install sqlcipher3-binary")
    sys.exit(1)

import sqlite3
import config

SOURCE_DB = config.DATABASE
ENCRYPTED_DB = SOURCE_DB.replace('.db', '_encrypted.db')
BACKUP_DB = SOURCE_DB.replace('.db', '_backup.db')


def migrate():
    """Migrate unencrypted database to encrypted format."""

    if not os.path.exists(SOURCE_DB):
        print(f"ERROR: Source database not found: {SOURCE_DB}")
        sys.exit(1)

    # Check if source database is already encrypted
    try:
        test_conn = sqlite3.connect(SOURCE_DB)
        test_conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        test_conn.close()
    except sqlite3.DatabaseError as e:
        print(f"Database appears to be already encrypted (or corrupted).")
        print(f"Error: {e}")
        print("This migration only works on unencrypted databases.")
        print("If your database is already encrypted, no migration is needed.")
        sys.exit(0)

    if os.path.exists(ENCRYPTED_DB):
        print(f"WARNING: Encrypted database already exists: {ENCRYPTED_DB}")
        response = input("Overwrite? (y/N): ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)
        os.remove(ENCRYPTED_DB)

    print(f"Migrating {SOURCE_DB} to encrypted format...")

    # Open source (unencrypted)
    source_conn = sqlite3.connect(SOURCE_DB)
    source_conn.row_factory = sqlite3.Row

    # Create encrypted database
    dest_conn = sqlcipher.connect(ENCRYPTED_DB)
    safe_key = SQLCIPHER_KEY.replace('"', '""')
    dest_conn.execute(f'PRAGMA key = "{safe_key}"')

    # Get schema and data from source
    cursor = source_conn.cursor()

    # Export schema (skip internal sqlite_ tables)
    cursor.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='table'
        AND sql IS NOT NULL
        AND name NOT LIKE 'sqlite_%'
    """)
    tables = cursor.fetchall()

    for table in tables:
        if table[0]:
            dest_conn.execute(table[0])

    # Export indexes (skip auto-created ones)
    cursor.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='index'
        AND sql IS NOT NULL
        AND name NOT LIKE 'sqlite_%'
    """)
    indexes = cursor.fetchall()

    for index in indexes:
        if index[0]:
            dest_conn.execute(index[0])

    dest_conn.commit()

    # Copy data from each table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = [row[0] for row in cursor.fetchall()]

    for table_name in table_names:
        if table_name.startswith('sqlite_'):
            continue

        # Get column count
        cursor.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()

        if rows:
            # Get column names
            columns = [description[0] for description in cursor.description]
            placeholders = ', '.join(['?' for _ in columns])
            column_list = ', '.join(columns)

            insert_sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"

            for row in rows:
                dest_conn.execute(insert_sql, tuple(row))

            print(f"  Copied {len(rows)} rows from {table_name}")

    dest_conn.commit()
    source_conn.close()
    dest_conn.close()

    print(f"\nEncrypted database created: {ENCRYPTED_DB}")
    print("\nTo complete migration:")
    print(f"  1. Backup: mv {SOURCE_DB} {BACKUP_DB}")
    print(f"  2. Replace: mv {ENCRYPTED_DB} {SOURCE_DB}")
    print(f"  3. Set SQLCIPHER_KEY in your environment/systemd service")

    response = input("\nAutomatically replace original database with backup? (y/N): ").strip().lower()
    if response == 'y':
        shutil.move(SOURCE_DB, BACKUP_DB)
        shutil.move(ENCRYPTED_DB, SOURCE_DB)
        print(f"\nMigration complete!")
        print(f"  Original backed up to: {BACKUP_DB}")
        print(f"  Encrypted database now at: {SOURCE_DB}")
        print(f"\nIMPORTANT: Add SQLCIPHER_KEY to your environment!")
    else:
        print("\nManual steps required. See instructions above.")


if __name__ == '__main__':
    migrate()
