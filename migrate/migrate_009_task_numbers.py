#!/usr/bin/env python3
"""
Migration script to add 'number' field to tasks and extract numbers from existing task names.
"""
import os
import re
import config


def extract_task_number(name):
    """Extract first number from task name.

    Examples:
        "Aufgabe 1" -> 1
        "Task 10" -> 10
        "Übung 5: Titel" -> 5
        "No number here" -> 0
    """
    match = re.search(r'\d+', name)
    return int(match.group()) if match else 0


def main():
    print("=" * 60)
    print("Task Number Migration")
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
        print("\n1. Checking if 'number' column exists...")
        columns = cursor.execute("PRAGMA table_info(task)").fetchall()
        column_names = [col['name'] for col in columns]

        if 'number' in column_names:
            print("   ✓ Column 'number' already exists")
        else:
            print("   Adding 'number' column...")
            cursor.execute("ALTER TABLE task ADD COLUMN number INTEGER DEFAULT 0")
            conn.commit()
            print("   ✓ Column 'number' added successfully")

        # Step 2: Extract numbers from task names
        print("\n2. Extracting numbers from task names...")
        tasks = cursor.execute("SELECT id, name, number FROM task").fetchall()

        if not tasks:
            print("   No tasks found in database")
            return

        updates = []
        for task in tasks:
            extracted_number = extract_task_number(task['name'])
            current_number = task['number'] or 0

            # Only update if current number is 0 (default)
            if current_number == 0 and extracted_number > 0:
                updates.append((extracted_number, task['id'], task['name']))

        if updates:
            print(f"   Found {len(updates)} tasks to update:")
            for number, task_id, name in updates:
                print(f"      Task {task_id}: \"{name}\" -> number = {number}")
                cursor.execute("UPDATE task SET number = ? WHERE id = ?", (number, task_id))

            conn.commit()
            print(f"   ✓ Updated {len(updates)} tasks")
        else:
            print("   No tasks need updating (all already have numbers)")

        # Step 3: Display final state
        print("\n3. Final task list (ordered by fach, stufe, number, name):")
        tasks = cursor.execute("""
            SELECT id, name, number, fach, stufe
            FROM task
            ORDER BY fach, stufe, number, name
        """).fetchall()

        current_fach = None
        current_stufe = None
        for task in tasks:
            if task['fach'] != current_fach or task['stufe'] != current_stufe:
                print(f"\n   {task['fach']} ({task['stufe']}):")
                current_fach = task['fach']
                current_stufe = task['stufe']
            print(f"      [{task['number']:3d}] {task['name']}")

        print("\n" + "=" * 60)
        print("Migration complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
