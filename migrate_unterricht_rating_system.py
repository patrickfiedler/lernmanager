#!/usr/bin/env python3
"""
Migration script for unterricht rating system changes.

Changes:
1. Add kommentar column to unterricht table (lesson-wide comment)
2. Change rating columns from INTEGER to TEXT in unterricht_student
3. Migrate existing data: 1 → "-", 2 → "ok", 3 → "+"

Usage:
    python migrate_unterricht_rating_system.py [path_to_database]

If no path is provided, uses data/mbi_tracker.db
"""

import sqlite3
import sys
import os
from datetime import datetime


def migrate_database(db_path):
    """Perform the migration."""

    # Backup first
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Creating backup: {backup_path}")

    import shutil
    shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        print("\n=== Starting Migration ===\n")

        # Step 1: Check if unterricht.kommentar already exists
        cursor.execute("PRAGMA table_info(unterricht)")
        columns = [col['name'] for col in cursor.fetchall()]

        if 'kommentar' not in columns:
            print("1. Adding kommentar column to unterricht table...")
            cursor.execute("ALTER TABLE unterricht ADD COLUMN kommentar TEXT")
            print("   ✓ Column added")
        else:
            print("1. kommentar column already exists in unterricht table")

        # Step 2: Check current schema of unterricht_student
        cursor.execute("PRAGMA table_info(unterricht_student)")
        rating_columns = {col['name']: col['type'] for col in cursor.fetchall()
                         if col['name'] in ['admin_selbststaendigkeit', 'admin_respekt', 'admin_fortschritt']}

        needs_migration = any(col_type == 'INTEGER' for col_type in rating_columns.values())

        if needs_migration:
            print("\n2. Migrating rating columns from INTEGER to TEXT...")

            # Get existing data
            cursor.execute("SELECT * FROM unterricht_student")
            existing_data = cursor.fetchall()
            print(f"   Found {len(existing_data)} records to migrate")

            # Create new table with TEXT columns
            print("   Creating new table schema...")
            cursor.execute("""
                CREATE TABLE unterricht_student_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    unterricht_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    anwesend INTEGER NOT NULL DEFAULT 1,
                    admin_selbststaendigkeit TEXT DEFAULT 'ok',
                    admin_respekt TEXT DEFAULT 'ok',
                    admin_fortschritt TEXT DEFAULT 'ok',
                    admin_kommentar TEXT,
                    selbst_selbststaendigkeit INTEGER,
                    selbst_respekt INTEGER,
                    has_been_saved INTEGER DEFAULT 0,
                    FOREIGN KEY (unterricht_id) REFERENCES unterricht(id),
                    FOREIGN KEY (student_id) REFERENCES student(id)
                )
            """)

            # Migration mapping
            value_map = {1: '-', 2: 'ok', 3: '+'}

            # Migrate data
            print("   Migrating data with value conversion (1→-, 2→ok, 3→+)...")
            for row in existing_data:
                # Convert INTEGER values to TEXT
                admin_selbst = value_map.get(row['admin_selbststaendigkeit'], 'ok')
                admin_respekt = value_map.get(row['admin_respekt'], 'ok')
                admin_fortschritt = value_map.get(row['admin_fortschritt'], 'ok')

                cursor.execute("""
                    INSERT INTO unterricht_student_new
                    (id, unterricht_id, student_id, anwesend,
                     admin_selbststaendigkeit, admin_respekt, admin_fortschritt, admin_kommentar,
                     selbst_selbststaendigkeit, selbst_respekt, has_been_saved)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row['id'], row['unterricht_id'], row['student_id'], row['anwesend'],
                    admin_selbst, admin_respekt, admin_fortschritt, row['admin_kommentar'],
                    row['selbst_selbststaendigkeit'], row['selbst_respekt'], row['has_been_saved']
                ))

            # Drop old table and rename new one
            print("   Replacing old table with new schema...")
            cursor.execute("DROP TABLE unterricht_student")
            cursor.execute("ALTER TABLE unterricht_student_new RENAME TO unterricht_student")

            print(f"   ✓ Successfully migrated {len(existing_data)} records")
        else:
            print("\n2. Rating columns already use TEXT type - no migration needed")

        # Commit changes
        conn.commit()

        print("\n=== Migration Complete ===")
        print(f"\nBackup saved to: {backup_path}")
        print("\nVerification:")

        # Verify schema
        cursor.execute("PRAGMA table_info(unterricht)")
        print("\nunterrricht table columns:")
        for col in cursor.fetchall():
            if col['name'] == 'kommentar':
                print(f"  ✓ {col['name']} {col['type']}")

        cursor.execute("PRAGMA table_info(unterricht_student)")
        print("\nunterrricht_student rating columns:")
        for col in cursor.fetchall():
            if col['name'] in ['admin_selbststaendigkeit', 'admin_respekt', 'admin_fortschritt']:
                print(f"  ✓ {col['name']} {col['type']} DEFAULT {col['dflt_value']}")

        # Show sample data
        cursor.execute("SELECT COUNT(*) as count FROM unterricht_student")
        count = cursor.fetchone()['count']
        print(f"\nTotal records in unterricht_student: {count}")

        if count > 0:
            cursor.execute("""
                SELECT admin_selbststaendigkeit, admin_respekt, admin_fortschritt
                FROM unterricht_student
                LIMIT 5
            """)
            print("\nSample rating values (first 5 records):")
            for row in cursor.fetchall():
                print(f"  Selbstständigkeit: {row['admin_selbststaendigkeit']}, "
                      f"Respekt: {row['admin_respekt']}, "
                      f"Fortschritt: {row['admin_fortschritt']}")

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
