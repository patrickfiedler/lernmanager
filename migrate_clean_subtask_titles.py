#!/usr/bin/env python3
"""
Migration: Clean up subtask titles.

Removes redundant numbering from subtask descriptions since the UI
already handles numbering and it shifts with visibility settings.

Before: "🔧 TEILAUFGABE 1: Hardware-Detektiv (PFLICHT)"
After:  "🔧 Hardware-Detektiv (PFLICHT)"

Usage:
    python migrate_clean_subtask_titles.py --dry-run   # preview changes
    python migrate_clean_subtask_titles.py              # apply changes
"""
import re
import sys

import models


def clean_title(beschreibung):
    """Clean the first line of a subtask description.

    TODO(human): Use re.sub() to remove these patterns from the first line:
        - "TEILAUFGABE <number>: " (e.g. "TEILAUFGABE 1: ", "TEILAUFGABE 10: ")
        - "BONUS <number>: " but keep the word "BONUS" (e.g. "BONUS 1: " → "BONUS: ")

    Hint: Only modify the FIRST line. Split on '\n', clean lines[0], rejoin.
    Hint: re.sub(r'pattern', 'replacement', string) returns the cleaned string.
    Hint: \d+ matches one or more digits, \s* matches optional whitespace.
    """
    lines = beschreibung.split('\n')
    # TODO(human): Clean lines[0] using two re.sub() calls
    lines[0] = re.sub(r'TEILAUFGABE \d+:\s*', '', lines[0])
    lines[0] = re.sub(r'(BONUS) \d+:\s*', r'Bonus: ', lines[0])
    lines[0] = re.sub(r'PFLICHT', 'Pflicht', lines[0])
    lines[0] = re.sub(r'\s*\(FREIWILLIG\)\s*', '', lines[0])
    return '\n'.join(lines)


def main():
    dry_run = '--dry-run' in sys.argv

    models.init_db()

    with models.db_session() as conn:
        rows = conn.execute(
            "SELECT id, beschreibung FROM subtask ORDER BY task_id, reihenfolge"
        ).fetchall()

        changed = 0
        for row in rows:
            old = row['beschreibung']
            new = clean_title(old)

            if old != new:
                changed += 1
                # Show first line before/after
                old_title = old.split('\n')[0][:70]
                new_title = new.split('\n')[0][:70]
                print(f"  {old_title}")
                print(f"  → {new_title}")
                print()

                if not dry_run:
                    conn.execute(
                        "UPDATE subtask SET beschreibung = ? WHERE id = ?",
                        (new, row['id'])
                    )

    if dry_run:
        print(f"[DRY RUN] Would update {changed} subtasks.")
    else:
        print(f"Updated {changed} subtasks.")


if __name__ == '__main__':
    main()
