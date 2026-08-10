"""Schema parity guard: every column in init_db() must be traceable to a
migration file, except for a frozen baseline of columns that predate the
migrate/ chain.

Why a baseline is needed: migrate_001 assumes tables like `student` already
exist (it only ALTERs them, never creates them) - the migration chain isn't
self-bootstrapping, it patches an ancient pre-migrate_001 schema that no
longer exists anywhere as runnable code (today's init_db() already has every
migration's changes baked in). So "run the full chain from scratch" can't be
tested directly; BASELINE_EXEMPT stands in for that ancient starting point.

What this catches: someone adds a column/table directly to init_db() (e.g.
while building a new feature) and forgets to also write the matching
migrate_0NN_*.py that existing production DBs need to catch up. This
happened 3x before (018-023, 029-030) - see todo.md "Schema parity guard".

What this can't catch: column *type* or *constraint* mismatches between
init_db() and a migration - this is a regex scan over CREATE TABLE / ALTER
TABLE statements, not a real SQL parser. It only proves a migration mentions
the column at all. Good enough to catch a fully-missing migration; not a
substitute for testing the migration's actual effect.
"""
import glob
import os
import re
import sqlite3

import config

MIGRATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrate')

CREATE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\n\s*\)", re.IGNORECASE | re.DOTALL)
ALTER_ADD_RE = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.IGNORECASE)
RENAME_RE = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+RENAME\s+TO\s+(\w+)", re.IGNORECASE)
CONSTRAINT_KEYWORDS = {'PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'CONSTRAINT'}


def _split_top_level_commas(body):
    """Split a CREATE TABLE column body on commas, ignoring commas nested
    inside parens (e.g. inside `PRIMARY KEY (a, b)` or `REFERENCES x(y)`)."""
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    parts.append(''.join(current))
    return parts


def _columns_covered_by_migrations():
    """(table, column) pairs mentioned by any migrate/*.py CREATE TABLE or
    ALTER TABLE ADD COLUMN statement. Follows `_new` rebuild+RENAME TO
    patterns (see migrate_004, migrate_036) back to the real table name."""
    covered = set()
    for path in sorted(glob.glob(os.path.join(MIGRATE_DIR, 'migrate_*.py'))):
        src = open(path, encoding='utf-8').read()
        renames = {m.group(1).lower(): m.group(2).lower() for m in RENAME_RE.finditer(src)}

        for m in ALTER_ADD_RE.finditer(src):
            table = renames.get(m.group(1).lower(), m.group(1).lower())
            covered.add((table, m.group(2).lower()))

        for m in CREATE_RE.finditer(src):
            table = renames.get(m.group(1).lower(), m.group(1).lower())
            for line in _split_top_level_commas(m.group(2)):
                line = line.strip().strip('"').strip("'")
                if not line:
                    continue
                first_word = line.split()[0].strip('"').strip("'").upper()
                if first_word in CONSTRAINT_KEYWORDS:
                    continue
                covered.add((table, first_word.lower()))
    return covered


def _init_db_columns(db_path):
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]
    columns = set()
    for t in tables:
        for row in conn.execute(f"PRAGMA table_info({t})").fetchall():
            columns.add((t.lower(), row[1].lower()))
    conn.close()
    return columns


# Columns that predate migrate_001 - see module docstring. Frozen at the
# point this guard was added (2026-08-09). Any init_db() column NOT in this
# set must be traceable to a migration file.
BASELINE_EXEMPT = {
    ('admin', 'id'), ('admin', 'password_hash'), ('admin', 'username'),
    ('analytics_events', 'event_type'), ('analytics_events', 'id'),
    ('analytics_events', 'metadata'), ('analytics_events', 'timestamp'),
    ('analytics_events', 'user_id'), ('analytics_events', 'user_type'),
    ('class_schedule', 'id'), ('class_schedule', 'klasse_id'), ('class_schedule', 'weekday'),
    ('error_log', 'id'), ('error_log', 'level'), ('error_log', 'message'),
    ('error_log', 'method'), ('error_log', 'route'), ('error_log', 'timestamp'),
    ('error_log', 'traceback'), ('error_log', 'url'), ('error_log', 'user_id'),
    ('error_log', 'user_type'),
    ('klasse', 'id'), ('klasse', 'name'),
    ('material', 'beschreibung'), ('material', 'id'), ('material', 'pfad'),
    ('material', 'task_id'), ('material', 'typ'),
    ('quiz_attempt', 'antworten_json'), ('quiz_attempt', 'bestanden'), ('quiz_attempt', 'id'),
    ('quiz_attempt', 'max_punkte'), ('quiz_attempt', 'punkte'),
    ('quiz_attempt', 'student_task_id'), ('quiz_attempt', 'timestamp'),
    ('saved_reports', 'date_from'), ('saved_reports', 'date_generated'),
    ('saved_reports', 'date_to'), ('saved_reports', 'filename'), ('saved_reports', 'id'),
    ('saved_reports', 'klasse_id'), ('saved_reports', 'report_type'), ('saved_reports', 'student_id'),
    ('student', 'id'), ('student', 'nachname'), ('student', 'password_hash'),
    ('student', 'username'), ('student', 'vorname'),
    ('student_klasse', 'klasse_id'), ('student_klasse', 'student_id'),
    ('student_subtask', 'erledigt'), ('student_subtask', 'id'),
    ('student_subtask', 'student_task_id'), ('student_subtask', 'subtask_id'),
    ('subtask', 'beschreibung'), ('subtask', 'id'), ('subtask', 'reihenfolge'), ('subtask', 'task_id'),
    ('subtask_visibility', 'enabled'), ('subtask_visibility', 'klasse_id'),
    ('subtask_visibility', 'set_by_admin_id'),
    ('task', 'beschreibung'), ('task', 'fach'), ('task', 'id'), ('task', 'kategorie'),
    ('task', 'lernziel'), ('task', 'name'), ('task', 'quiz_json'), ('task', 'stufe'),
    ('task_folge', 'folge_task_id'), ('task_folge', 'task_id'),
    ('task_voraussetzung', 'task_id'), ('task_voraussetzung', 'voraussetzung_task_id'),
    ('unterricht', 'datum'), ('unterricht', 'id'), ('unterricht', 'klasse_id'),
}


def test_every_non_baseline_column_has_a_migration(db):
    target = _init_db_columns(config.DATABASE)
    covered = _columns_covered_by_migrations()

    missing = target - covered - BASELINE_EXEMPT
    assert not missing, (
        "These init_db() columns have no matching migrate/*.py statement and "
        "aren't in BASELINE_EXEMPT - existing production DBs will silently "
        f"lack them until a migration is written: {sorted(missing)}"
    )

    stale = BASELINE_EXEMPT - target
    assert not stale, (
        "BASELINE_EXEMPT lists columns no longer in init_db() - remove them "
        f"to keep the baseline accurate: {sorted(stale)}"
    )
