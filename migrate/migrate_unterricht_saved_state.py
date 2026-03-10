#!/usr/bin/env python3
"""
Migration script to add 'has_been_saved' field to unterricht_student table.
"""
import os
import config


def main():
    print("=" * 60)
    print("Unterricht Saved State Migration")
    print("=" * 60)

    # Check if we're using SQLCipher
    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    if sqlcipher_key:
        print("✓ Using SQLCipher (encrypted database)")
        try:
            from sqlcipher3 import dbapi2 as sqlite3
        except ImportError:
            print("✗ sqlcipher3 not installed")
            print("  Install with: pip install sqlcipher3-binary")
            import sys
            sys.exit(1)
    else:
        print("✓ Using standard SQLite (unencrypted database)")
        import sqlite3

    # Connect to database
    conn = sqlite3.connect(config.DATABASE)
    if sqlcipher_key:
        conn.execute(f"PRAGMA key = '{sqlcipher_key}'")
        print("✓ Encryption key set")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Step 1: Check if column already exists
        print("\n1. Checking if 'has_been_saved' column exists...")
        columns = cursor.execute("PRAGMA table_info(unterricht_student)").fetchall()
        column_names = [col['name'] for col in columns]

        if 'has_been_saved' in column_names:
            print("   ✓ Column 'has_been_saved' already exists")
        else:
            print("   Adding 'has_been_saved' column...")
            cursor.execute("ALTER TABLE unterricht_student ADD COLUMN has_been_saved INTEGER DEFAULT 0")
            conn.commit()
            print("   ✓ Column 'has_been_saved' added successfully")

        # Step 2: Set existing records to has_been_saved = 0 (show as unsaved/defaults)
        print("\n2. Initializing existing records...")
        result = cursor.execute("UPDATE unterricht_student SET has_been_saved = 0 WHERE has_been_saved IS NULL")
        conn.commit()
        print(f"   ✓ Initialized {result.rowcount} records with has_been_saved = 0")

        # Step 3: Display summary
        print("\n3. Summary:")
        total = cursor.execute("SELECT COUNT(*) as count FROM unterricht_student").fetchone()['count']
        print(f"   Total unterricht_student records: {total}")
        print(f"   All records initialized with has_been_saved = 0 (defaults)")

        print("\n" + "=" * 60)
        print("Migration complete!")
        print("=" * 60)
        print("\nNote: All existing evaluations will show as 'unsaved' (lighter colors)")
        print("until admin clicks a rating button, which will mark them as saved.")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
