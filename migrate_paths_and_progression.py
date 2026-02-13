#!/usr/bin/env python3
"""
Database Migration: Learning Paths + Topic Progression

Combined migration for the learning paths and topic progression features.
Changes:
  - subtask: add path, path_model, graded_artifact_json columns
  - student: add lernpfad column
  - student_task: recreate table (drop UNIQUE constraint, add rolle, drop current_subtask_id)
  - New topic_queue table

Must run BEFORE deploying Phase 2+ code changes.
"""

import os
import sys
import shutil
from datetime import datetime

DB_PATH = 'data/mbi_tracker.db'


def get_sqlite(sqlcipher_key):
    """Return the appropriate sqlite3 module."""
    if sqlcipher_key:
        try:
            from sqlcipher3 import dbapi2 as sqlite3
            return sqlite3
        except ImportError:
            print("✗ sqlcipher3 not installed")
            print("  Install with: pip install sqlcipher3-binary")
            sys.exit(1)
    else:
        import sqlite3
        return sqlite3


def connect(sqlite3, sqlcipher_key):
    """Connect to the database and verify access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if sqlcipher_key:
        conn.execute(f"PRAGMA key = '{sqlcipher_key}'")
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            print("✗ Failed to decrypt database with provided key")
            sys.exit(1)
    return conn


def get_columns(conn, table):
    """Return list of column names for a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def table_exists(conn, table):
    """Check if a table exists."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone()
    return row[0] > 0


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        print("  Run this migration from the project root directory")
        sys.exit(1)

    sqlcipher_key = os.environ.get('SQLCIPHER_KEY')
    if sqlcipher_key:
        print("✓ Using SQLCipher (encrypted database)")
    else:
        print("✓ Using standard SQLite (unencrypted database)")

    sqlite3 = get_sqlite(sqlcipher_key)

    print()
    print("=" * 70)
    print("Migration: Learning Paths + Topic Progression")
    print("=" * 70)

    # Step 1: Backup
    print("\nStep 1: Creating backup...")
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created: {backup_path}")

    conn = connect(sqlite3, sqlcipher_key)

    # Step 2: Add columns to subtask table
    print("\nStep 2: Adding columns to subtask table...")
    subtask_cols = get_columns(conn, 'subtask')

    for col, definition in [
        ('path', "ALTER TABLE subtask ADD COLUMN path TEXT"),
        ('path_model', "ALTER TABLE subtask ADD COLUMN path_model TEXT DEFAULT 'skip'"),
        ('graded_artifact_json', "ALTER TABLE subtask ADD COLUMN graded_artifact_json TEXT"),
    ]:
        if col in subtask_cols:
            print(f"  ✓ '{col}' already exists")
        else:
            conn.execute(definition)
            conn.commit()
            print(f"  ✓ Added '{col}'")

    # Set existing subtasks to wanderweg (safe default — all paths include these)
    updated = conn.execute(
        "UPDATE subtask SET path = 'wanderweg' WHERE path IS NULL"
    ).rowcount
    conn.commit()
    if updated:
        print(f"  ✓ Set {updated} existing subtasks to path='wanderweg'")

    # Step 3: Add lernpfad to student table
    print("\nStep 3: Adding lernpfad to student table...")
    student_cols = get_columns(conn, 'student')

    if 'lernpfad' in student_cols:
        print("  ✓ 'lernpfad' already exists")
    else:
        conn.execute("ALTER TABLE student ADD COLUMN lernpfad TEXT DEFAULT 'bergweg'")
        conn.commit()
        print("  ✓ Added 'lernpfad' (default: bergweg)")

    # Step 4: Recreate student_task table
    # This is the complex part: drop UNIQUE(student_id, klasse_id), add rolle, drop current_subtask_id
    # Must preserve id values for FK references from student_subtask, quiz_attempt, game_task_progress
    print("\nStep 4: Recreating student_task table...")
    student_task_cols = get_columns(conn, 'student_task')

    needs_recreation = 'current_subtask_id' in student_task_cols or 'rolle' not in student_task_cols
    if not needs_recreation:
        print("  ✓ student_task already has correct schema")
    else:
        # Count existing data for verification
        before_count = conn.execute("SELECT COUNT(*) FROM student_task").fetchone()[0]
        before_max_id = conn.execute("SELECT MAX(id) FROM student_task").fetchone()[0]

        # Check child table counts for integrity verification
        child_counts = {}
        for child_table in ['student_subtask', 'quiz_attempt', 'game_task_progress']:
            if table_exists(conn, child_table):
                child_counts[child_table] = conn.execute(
                    f"SELECT COUNT(*) FROM {child_table}"
                ).fetchone()[0]

        # Disable foreign keys for the table swap
        conn.execute("PRAGMA foreign_keys = OFF")

        try:
            # Create new table (no UNIQUE constraint, no current_subtask_id, has rolle)
            conn.execute('''
                CREATE TABLE student_task_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    klasse_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    abgeschlossen INTEGER NOT NULL DEFAULT 0,
                    manuell_abgeschlossen INTEGER NOT NULL DEFAULT 0,
                    rolle TEXT NOT NULL DEFAULT 'primary',
                    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                    FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
                )
            ''')

            # Copy data (all existing rows get rolle='primary')
            conn.execute('''
                INSERT INTO student_task_new
                    (id, student_id, klasse_id, task_id, abgeschlossen, manuell_abgeschlossen, rolle)
                SELECT id, student_id, klasse_id, task_id, abgeschlossen, manuell_abgeschlossen, 'primary'
                FROM student_task
            ''')

            # Swap tables
            conn.execute("DROP TABLE student_task")
            conn.execute("ALTER TABLE student_task_new RENAME TO student_task")

            conn.commit()

            # Verify data integrity
            after_count = conn.execute("SELECT COUNT(*) FROM student_task").fetchone()[0]
            after_max_id = conn.execute("SELECT MAX(id) FROM student_task").fetchone()[0]

            if after_count != before_count:
                raise RuntimeError(
                    f"Row count mismatch: {before_count} → {after_count}"
                )
            if before_max_id is not None and after_max_id != before_max_id:
                raise RuntimeError(
                    f"Max ID mismatch: {before_max_id} → {after_max_id}"
                )

            # Verify child tables still intact
            for child_table, expected in child_counts.items():
                actual = conn.execute(
                    f"SELECT COUNT(*) FROM {child_table}"
                ).fetchone()[0]
                if actual != expected:
                    raise RuntimeError(
                        f"{child_table} count changed: {expected} → {actual}"
                    )

            print(f"  ✓ Recreated student_task ({after_count} rows preserved)")
            print("    - Dropped UNIQUE(student_id, klasse_id)")
            print("    - Dropped current_subtask_id column")
            print("    - Added rolle column (all existing = 'primary')")

        except Exception as e:
            conn.rollback()
            print(f"  ✗ Error during student_task recreation: {e}")
            print(f"  Restoring from backup: {backup_path}")
            conn.close()
            shutil.copy2(backup_path, DB_PATH)
            sys.exit(1)
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    # Step 5: Create topic_queue table
    print("\nStep 5: Creating topic_queue table...")
    if table_exists(conn, 'topic_queue'):
        print("  ✓ topic_queue already exists")
    else:
        conn.execute('''
            CREATE TABLE topic_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                UNIQUE(klasse_id, task_id),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
        print("  ✓ Created topic_queue table")

    # Step 6: Foreign key integrity check
    print("\nStep 6: Verifying foreign key integrity...")
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        print(f"  ⚠ Found {len(fk_violations)} FK violations:")
        for v in fk_violations[:10]:
            print(f"    {v[0]} rowid={v[1]} → {v[2]}")
        print("  These may be pre-existing issues. Review manually.")
    else:
        print("  ✓ All foreign key references valid")

    # Step 7: Final verification
    print("\nStep 7: Final verification...")
    for table, expected_cols in [
        ('subtask', ['path', 'path_model', 'graded_artifact_json']),
        ('student', ['lernpfad']),
        ('student_task', ['rolle']),
    ]:
        cols = get_columns(conn, table)
        for col in expected_cols:
            if col in cols:
                print(f"  ✓ {table}.{col}")
            else:
                print(f"  ✗ {table}.{col} MISSING")

    # Verify current_subtask_id is gone
    st_cols = get_columns(conn, 'student_task')
    if 'current_subtask_id' not in st_cols:
        print("  ✓ student_task.current_subtask_id removed")
    else:
        print("  ✗ student_task.current_subtask_id still present")

    if table_exists(conn, 'topic_queue'):
        print("  ✓ topic_queue table exists")
    else:
        print("  ✗ topic_queue table MISSING")

    conn.close()

    print("\n" + "=" * 70)
    print("Migration completed successfully!")
    print("=" * 70)
    print()
    print("Summary:")
    print("  - subtask: +path, +path_model, +graded_artifact_json")
    print("  - student: +lernpfad (default: bergweg)")
    print("  - student_task: -UNIQUE, -current_subtask_id, +rolle")
    print("  - topic_queue: new table")
    print()
    print("Next: Deploy Phase 2 code (models.py changes)")
    print()


if __name__ == '__main__':
    migrate()
