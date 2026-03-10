#!/usr/bin/env python3
"""
Migration: Add subtask_visibility table for flexible subtask management

This migration adds a new table to track which subtasks are visible/enabled
for classes and individual students, replacing the limited single-subtask
focus of current_subtask_id.

Features:
- Enable/disable individual subtasks per class or student
- Individual student rules override class rules
- Backward compatible (no rules = all subtasks visible)
- Audit trail (who enabled/disabled, when)

Usage:
    python migrate_subtask_visibility.py

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

def check_table_exists(cursor):
    """Check if subtask_visibility table already exists."""
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='subtask_visibility'
    """)
    return cursor.fetchone() is not None

def migrate():
    """Run the migration."""
    print("\n" + "="*70)
    print("Migration: Add subtask_visibility table")
    print("="*70 + "\n")

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

    # Step 3: Check if table already exists
    print("\nStep 3: Checking if table already exists...")
    if check_table_exists(cursor):
        print("✓ Table 'subtask_visibility' already exists - migration already applied")
        print("\nNothing to do. Migration complete.")
        conn.close()
        return

    # Step 4: Create the table
    print("\nStep 4: Creating 'subtask_visibility' table...")
    try:
        cursor.execute("""
            CREATE TABLE subtask_visibility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subtask_id INTEGER NOT NULL,

                -- Context: either class-wide OR individual student
                klasse_id INTEGER,
                student_id INTEGER,

                -- Visibility flag (1 = enabled/visible, 0 = disabled/hidden)
                enabled INTEGER DEFAULT 1,

                -- Audit trail
                set_by_admin_id INTEGER,
                set_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Foreign keys
                FOREIGN KEY (subtask_id) REFERENCES subtask(id) ON DELETE CASCADE,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (set_by_admin_id) REFERENCES admin(id),

                -- Constraint: either class-wide OR individual, not both
                CHECK (
                    (klasse_id IS NOT NULL AND student_id IS NULL) OR
                    (klasse_id IS NULL AND student_id IS NOT NULL)
                )
            )
        """)
        conn.commit()
        print("✓ Table created successfully")
    except Exception as e:
        print(f"ERROR: Failed to create table: {e}", file=sys.stderr)
        conn.rollback()
        conn.close()
        sys.exit(1)

    # Step 5: Create indexes
    print("\nStep 5: Creating indexes for fast lookups...")
    try:
        cursor.execute("""
            CREATE INDEX idx_sv_subtask
            ON subtask_visibility(subtask_id)
        """)
        cursor.execute("""
            CREATE INDEX idx_sv_klasse
            ON subtask_visibility(klasse_id)
            WHERE klasse_id IS NOT NULL
        """)
        cursor.execute("""
            CREATE INDEX idx_sv_student
            ON subtask_visibility(student_id)
            WHERE student_id IS NOT NULL
        """)
        cursor.execute("""
            CREATE INDEX idx_sv_context
            ON subtask_visibility(subtask_id, klasse_id, student_id)
        """)
        conn.commit()
        print("✓ Indexes created successfully")
    except Exception as e:
        print(f"ERROR: Failed to create indexes: {e}", file=sys.stderr)
        conn.rollback()
        conn.close()
        sys.exit(1)

    # Step 6: Verify
    print("\nStep 6: Verifying migration...")
    if check_table_exists(cursor):
        print("✓ Verification successful - table exists")

        # Show table schema
        cursor.execute("PRAGMA table_info(subtask_visibility)")
        print("\nTable schema:")
        print("-" * 70)
        for row in cursor.fetchall():
            col_id, name, col_type, not_null, default, pk = row
            nullable = "NOT NULL" if not_null else "NULL"
            pk_marker = " (PRIMARY KEY)" if pk else ""
            default_str = f" DEFAULT {default}" if default else ""
            print(f"  {name:20s} {col_type:10s} {nullable:8s}{default_str}{pk_marker}")
        print("-" * 70)

        # Show indexes
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='subtask_visibility'
        """)
        indexes = [row[0] for row in cursor.fetchall()]
        print(f"\nIndexes created: {len(indexes)}")
        for idx in indexes:
            print(f"  - {idx}")

    else:
        print("ERROR: Verification failed - table not found", file=sys.stderr)
        conn.close()
        sys.exit(1)

    conn.close()

    print("\n" + "="*70)
    print("✅ Migration completed successfully!")
    print("="*70)
    print(f"\nBackup saved at: {backup_path}")
    print("\nWhat this migration enables:")
    print("  1. Flexible enable/disable of individual subtasks")
    print("  2. Class-wide visibility rules")
    print("  3. Per-student overrides (override class settings)")
    print("  4. Backward compatible (no rules = all subtasks visible)")
    print("  5. Audit trail (who changed what, when)")
    print("\nNext steps:")
    print("  1. Implement new models functions (get_visible_subtasks_for_student, etc.)")
    print("  2. Create admin UI for managing subtask visibility")
    print("  3. Update student view to use new visibility system")
    print("  4. Test with existing assignments (should still work!)")
    print("\nNote: Existing assignments are not affected - they continue to work.")
    print("      The new system is opt-in until admins start setting visibility rules.")

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
