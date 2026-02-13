#!/usr/bin/env python3
"""
Migration: Normalize markdown formatting in subtask descriptions.

Fixes:
- \r\n → \n (Windows → Unix line endings)
- Consistent bold section headers (🎯 Ziel:, 📋 Aufgabe:, etc.)
- Remove stray ###/####/** from title lines

Usage:
    python migrate_normalize_markdown.py --dry-run   # preview changes
    python migrate_normalize_markdown.py              # apply changes
"""
import re
import sys

import models


def normalize_markdown(beschreibung):
    """Normalize markdown formatting for consistent rendering."""

    # === YOUR PART ===
    # TODO(human): Two tasks:
    #
    # 1. Replace \r\n with \n (one re.sub or str.replace call)
    #
    # 2. Make section markers bold. These appear at the START of a line:
    #      🎯 Ziel:    →  **🎯 Ziel:**
    #      📋 Aufgabe:  →  **📋 Aufgabe:**
    #      💡 Tipp:     →  **💡 Tipp:**
    #      ✅ Fertig wenn:  →  **✅ Fertig wenn:**
    #
    #    Hint: Use re.sub with a pattern that matches the emoji + label + colon
    #    at the start of a line. The flag re.MULTILINE makes ^ match every
    #    line start, not just the string start.
    #    Example: re.sub(r'^(🎯 Ziel:)', r'**\1**', text, flags=re.MULTILINE)
    #    But that's 4 separate calls. Can you do it in one?
    #    Hint: (A|B|C) matches A or B or C.
    #
    # Don't touch anything below this line.
    beschreibung = beschreibung.replace('\r\n', '\n')
    beschreibung = re.sub(r'^(🎯 Ziel:|📋 Aufgabe:|💡 Tipp:|✅ Fertig wenn:)', r'**\1**', beschreibung, flags=re.MULTILINE)
    
    # === END YOUR PART ===

    # === MY PART: Clean up inconsistent title formatting ===
    lines = beschreibung.split('\n')

    # Strip stray markdown from title line (line 0)
    # Remove leading ### or #### (some titles have them, most don't)
    lines[0] = re.sub(r'^#{1,4}\s*', '', lines[0])
    # Remove bold wrapper around entire title line
    lines[0] = re.sub(r'^\*\*(.+?)\*\*$', r'\1', lines[0])
    # Remove trailing ** that got orphaned (e.g. "### 🎭 ... (Pflicht)**")
    lines[0] = re.sub(r'\*\*$', '', lines[0])
    # Clean double spaces left behind
    lines[0] = re.sub(r'  +', ' ', lines[0]).strip()

    beschreibung = '\n'.join(lines)

    # Also fix section headers that already have partial bold
    # e.g. "**🎯 Ziel:** text" is correct, but "**🎯 Ziel: text**" wraps too much
    # Only fix if our bold-wrapping above created doubles like ****
    beschreibung = beschreibung.replace('****', '**')

    return beschreibung


def main():
    dry_run = '--dry-run' in sys.argv

    models.init_db()

    with models.db_session() as conn:
        rows = conn.execute(
            "SELECT id, task_id, reihenfolge, beschreibung FROM subtask ORDER BY task_id, reihenfolge"
        ).fetchall()

        changed = 0
        for row in rows:
            old = row['beschreibung']
            new = normalize_markdown(old)

            if old != new:
                changed += 1
                # Show title and what changed
                title = new.split('\n')[0][:70]
                print(f"  [{row['task_id']}/{row['reihenfolge']}] {title}")

                # Show specific changes
                old_lines = old.split('\n')
                new_lines = new.split('\n')
                diffs = 0
                for i, (o, n) in enumerate(zip(old_lines, new_lines)):
                    if o != n and diffs < 3:
                        print(f"    L{i}: {o[:60]}")
                        print(f"     → {n[:60]}")
                        diffs += 1
                if len(old_lines) != len(new_lines):
                    print(f"    Lines: {len(old_lines)} → {len(new_lines)}")
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
