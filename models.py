import json
import os
import sys
from hashlib import sha256
from contextlib import contextmanager
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import config

# Terminology mapping (UI German → Database English):
#   Thema (topic)       → task table
#   Aufgabe (task)      → subtask table
#   Schüler-Thema       → student_task table

# SQLCipher support: Use encrypted database if SQLCIPHER_KEY is set
SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
USE_SQLCIPHER = False

if SQLCIPHER_KEY:
    try:
        from sqlcipher3 import dbapi2 as sqlite3
        USE_SQLCIPHER = True
    except ImportError:
        import sqlite3
        print("WARNING: SQLCIPHER_KEY is set but sqlcipher3 is not installed.", file=sys.stderr)
        print("Database will NOT be encrypted. Install with: pip install sqlcipher3-binary", file=sys.stderr)
else:
    import sqlite3


def hash_password(password):
    """Hash password using werkzeug (bcrypt-based)."""
    return generate_password_hash(password)


def _legacy_hash(password):
    """Legacy SHA256 hash for migration."""
    return sha256(password.encode()).hexdigest()


def verify_password(stored_hash, password):
    """Verify password against stored hash.

    Supports both new bcrypt hashes and legacy SHA256 hashes.
    Returns (is_valid, needs_rehash).
    """
    # Try werkzeug hash first (starts with 'scrypt:' or 'pbkdf2:')
    if stored_hash.startswith(('scrypt:', 'pbkdf2:')):
        return check_password_hash(stored_hash, password), False

    # Try legacy SHA256 hash
    if stored_hash == _legacy_hash(password):
        return True, True  # Valid but needs rehash

    return False, False


def get_db():
    """Get database connection with optimized performance settings."""
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    if USE_SQLCIPHER and SQLCIPHER_KEY:
        # Set encryption key - escape any double quotes in key
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')

    # Performance optimizations for analytics logging
    # WAL mode: Write-Ahead Logging improves write concurrency and reduces fsync calls
    # synchronous=NORMAL: Safe with WAL mode, significantly faster than FULL
    # Expected improvement: 84ms -> 10-20ms per request on production VPS
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session():
    """Context manager for database operations."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database schema."""
    with db_session() as conn:
        conn.executescript('''
            -- Admin user
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );

            -- Classes (Klassen)
            CREATE TABLE IF NOT EXISTS klasse (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );

            -- Students (Schüler)
            CREATE TABLE IF NOT EXISTS student (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nachname TEXT NOT NULL,
                vorname TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                lernpfad TEXT DEFAULT 'bergweg'  -- wanderweg/bergweg/gipfeltour
            );

            -- Student-Class relationship (many-to-many)
            CREATE TABLE IF NOT EXISTS student_klasse (
                student_id INTEGER NOT NULL,
                klasse_id INTEGER NOT NULL,
                PRIMARY KEY (student_id, klasse_id),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE
            );

            -- Class schedule (day of week each class meets)
            CREATE TABLE IF NOT EXISTS class_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL UNIQUE,
                weekday INTEGER NOT NULL,  -- 0=Monday, 1=Tuesday, ..., 6=Sunday (ISO 8601)
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE
            );

            -- Tasks (Aufgaben)
            CREATE TABLE IF NOT EXISTS task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                number INTEGER DEFAULT 0,
                beschreibung TEXT,
                lernziel TEXT,
                lernziel_schueler TEXT,  -- student-facing version: "Du lernst..."
                fach TEXT NOT NULL,
                stufe TEXT NOT NULL,
                kategorie TEXT NOT NULL DEFAULT 'pflicht',  -- pflicht/bonus
                quiz_json TEXT,  -- JSON format for quiz questions (topic-level)
                why_learn_this TEXT,
                subtask_quiz_required INTEGER DEFAULT 1  -- 1=must pass subtask quizzes, 0=optional
            );

            -- Task prerequisites (many-to-many)
            CREATE TABLE IF NOT EXISTS task_voraussetzung (
                task_id INTEGER NOT NULL,
                voraussetzung_task_id INTEGER NOT NULL,
                PRIMARY KEY (task_id, voraussetzung_task_id),
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
                FOREIGN KEY (voraussetzung_task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Follow-up tasks (Folgeaufgaben)
            CREATE TABLE IF NOT EXISTS task_folge (
                task_id INTEGER NOT NULL,
                folge_task_id INTEGER NOT NULL,
                PRIMARY KEY (task_id, folge_task_id),
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
                FOREIGN KEY (folge_task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Elective task groups (Wahlpflicht)
            -- Students must complete ONE task from the group
            CREATE TABLE IF NOT EXISTS wahlpflicht_gruppe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                beschreibung TEXT,
                fach TEXT NOT NULL,
                stufe TEXT NOT NULL
            );

            -- Tasks belonging to an elective group
            CREATE TABLE IF NOT EXISTS wahlpflicht_task (
                gruppe_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                PRIMARY KEY (gruppe_id, task_id),
                FOREIGN KEY (gruppe_id) REFERENCES wahlpflicht_gruppe(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Sub-tasks (Teilaufgaben)
            CREATE TABLE IF NOT EXISTS subtask (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                beschreibung TEXT NOT NULL,
                reihenfolge INTEGER NOT NULL DEFAULT 0,
                estimated_minutes INTEGER,
                quiz_json TEXT,  -- per-subtask quiz JSON
                path TEXT,  -- wanderweg/bergweg/gipfeltour (lowest path that includes this task)
                path_model TEXT DEFAULT 'skip',  -- skip: lower paths skip; depth: all paths do it
                graded_artifact_json TEXT,  -- JSON: {keyword, format, rubric}
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Materials (Materialien)
            CREATE TABLE IF NOT EXISTS material (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                typ TEXT NOT NULL,  -- 'link' or 'datei'
                pfad TEXT NOT NULL,  -- URL or file path
                beschreibung TEXT,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Material-Subtask assignments (per-Aufgabe material visibility)
            -- No rows for a material = visible for ALL Aufgaben (backward compatible)
            CREATE TABLE IF NOT EXISTS material_subtask (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL,
                subtask_id INTEGER NOT NULL,
                UNIQUE(material_id, subtask_id),
                FOREIGN KEY (material_id) REFERENCES material(id) ON DELETE CASCADE,
                FOREIGN KEY (subtask_id) REFERENCES subtask(id) ON DELETE CASCADE
            );

            -- Student task assignment (per class)
            -- No UNIQUE: students can have multiple topics per class (primary + sidequests)
            CREATE TABLE IF NOT EXISTS student_task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                klasse_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                abgeschlossen INTEGER NOT NULL DEFAULT 0,
                manuell_abgeschlossen INTEGER NOT NULL DEFAULT 0,
                rolle TEXT NOT NULL DEFAULT 'primary',  -- primary/sidequest
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Student sub-task completion
            CREATE TABLE IF NOT EXISTS student_subtask (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_task_id INTEGER NOT NULL,
                subtask_id INTEGER NOT NULL,
                erledigt INTEGER NOT NULL DEFAULT 0,
                UNIQUE(student_task_id, subtask_id),
                FOREIGN KEY (student_task_id) REFERENCES student_task(id) ON DELETE CASCADE,
                FOREIGN KEY (subtask_id) REFERENCES subtask(id) ON DELETE CASCADE
            );

            -- Quiz attempts
            CREATE TABLE IF NOT EXISTS quiz_attempt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_task_id INTEGER NOT NULL,
                subtask_id INTEGER,  -- NULL = topic quiz, set = subtask quiz
                punkte INTEGER NOT NULL,
                max_punkte INTEGER NOT NULL,
                bestanden INTEGER NOT NULL,
                antworten_json TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_task_id) REFERENCES student_task(id) ON DELETE CASCADE
            );

            -- Subtask visibility (per-class and per-student overrides)
            CREATE TABLE IF NOT EXISTS subtask_visibility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subtask_id INTEGER NOT NULL,
                klasse_id INTEGER,
                student_id INTEGER,
                enabled INTEGER DEFAULT 1,
                set_by_admin_id INTEGER,
                set_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subtask_id) REFERENCES subtask(id) ON DELETE CASCADE,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (set_by_admin_id) REFERENCES admin(id),
                CHECK (
                    (klasse_id IS NOT NULL AND student_id IS NULL) OR
                    (klasse_id IS NULL AND student_id IS NOT NULL)
                )
            );

            CREATE INDEX IF NOT EXISTS idx_sv_subtask
            ON subtask_visibility(subtask_id);

            CREATE INDEX IF NOT EXISTS idx_sv_klasse
            ON subtask_visibility(klasse_id)
            WHERE klasse_id IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_sv_student
            ON subtask_visibility(student_id)
            WHERE student_id IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_sv_context
            ON subtask_visibility(subtask_id, klasse_id, student_id);

            -- Topic queue (ordered topic sequence per class)
            CREATE TABLE IF NOT EXISTS topic_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                UNIQUE(klasse_id, task_id),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Lessons (Unterricht)
            CREATE TABLE IF NOT EXISTS unterricht (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                datum DATE NOT NULL,
                kommentar TEXT,
                UNIQUE(klasse_id, datum),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE
            );

            -- Lesson attendance and evaluation
            CREATE TABLE IF NOT EXISTS unterricht_student (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unterricht_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                anwesend INTEGER NOT NULL DEFAULT 1,
                -- Admin evaluation (ratings: '-', 'ok', '+')
                admin_selbststaendigkeit TEXT DEFAULT 'ok',
                admin_respekt TEXT DEFAULT 'ok',
                admin_fortschritt TEXT DEFAULT 'ok',
                admin_kommentar TEXT,
                has_been_saved INTEGER DEFAULT 0,
                -- Student self-evaluation
                selbst_selbststaendigkeit INTEGER,
                selbst_respekt INTEGER,
                UNIQUE(unterricht_id, student_id),
                FOREIGN KEY (unterricht_id) REFERENCES unterricht(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );

            -- ============ Game Mode Tables ============

            -- Game character state for each student
            CREATE TABLE IF NOT EXISTS game_character (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER UNIQUE NOT NULL,
                fach TEXT NOT NULL,
                hp INTEGER NOT NULL DEFAULT 100,
                max_hp INTEGER NOT NULL DEFAULT 100,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                current_area TEXT DEFAULT 'village',
                position_x INTEGER DEFAULT 0,
                position_y INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );

            -- Question pool extracted from tasks for game encounters
            CREATE TABLE IF NOT EXISTS game_question_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                question_index INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                answers_json TEXT NOT NULL,
                correct_indices_json TEXT NOT NULL,
                difficulty INTEGER DEFAULT 1,
                fach TEXT NOT NULL,
                UNIQUE(task_id, question_index),
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Track which questions student has answered (for spaced repetition)
            CREATE TABLE IF NOT EXISTS game_question_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                question_pool_id INTEGER NOT NULL,
                times_answered INTEGER DEFAULT 0,
                times_correct INTEGER DEFAULT 0,
                last_answered DATETIME,
                next_review DATETIME,
                UNIQUE(student_id, question_pool_id),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (question_pool_id) REFERENCES game_question_pool(id) ON DELETE CASCADE
            );

            -- Track game answers that count toward real task completion
            CREATE TABLE IF NOT EXISTS game_task_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                student_task_id INTEGER NOT NULL,
                question_index INTEGER NOT NULL,
                answered_correctly INTEGER NOT NULL DEFAULT 0,
                answered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(student_id, student_task_id, question_index),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (student_task_id) REFERENCES student_task(id) ON DELETE CASCADE
            );

            -- Index for efficient question selection
            CREATE INDEX IF NOT EXISTS idx_question_pool_fach_difficulty
            ON game_question_pool(fach, difficulty);

            CREATE INDEX IF NOT EXISTS idx_question_history_review
            ON game_question_history(student_id, next_review);

            -- ============ Error Logging ============

            -- Error log for tracking application errors
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                level TEXT NOT NULL,  -- ERROR, WARNING, CRITICAL
                message TEXT NOT NULL,
                traceback TEXT,
                user_id INTEGER,
                user_type TEXT,  -- 'admin' or 'student'
                route TEXT,
                method TEXT,
                url TEXT
            );

            -- Index for efficient log retrieval and cleanup
            CREATE INDEX IF NOT EXISTS idx_error_log_timestamp
            ON error_log(timestamp DESC);

            -- ============ Analytics & Activity Logging ============

            -- Analytics events for both usage statistics and student activity logs
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,  -- 'login', 'page_view', 'file_download', 'task_start', 'subtask_complete', 'task_complete', 'quiz_attempt', 'self_eval'
                user_id INTEGER,
                user_type TEXT,  -- 'admin' or 'student'
                metadata TEXT    -- JSON format for flexible event data
            );

            -- Indexes for efficient querying
            CREATE INDEX IF NOT EXISTS idx_analytics_timestamp
            ON analytics_events(timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_analytics_user
            ON analytics_events(user_id, user_type, timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_analytics_type
            ON analytics_events(event_type, timestamp DESC);

            -- ============ App Settings ============

            -- Global application settings (key-value store)
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- ============ Saved Reports ============

            -- Stored PDF reports for historical comparison
            CREATE TABLE IF NOT EXISTS saved_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,  -- 'class_simple', 'student_summary', 'student_complete'
                klasse_id INTEGER,
                student_id INTEGER,
                date_generated DATETIME DEFAULT CURRENT_TIMESTAMP,
                date_from DATE,
                date_to DATE,
                filename TEXT NOT NULL
            );

            -- Index for efficient retrieval by class
            CREATE INDEX IF NOT EXISTS idx_saved_reports_klasse
            ON saved_reports(klasse_id, date_generated DESC);

            -- Index for efficient retrieval by student
            CREATE INDEX IF NOT EXISTS idx_saved_reports_student
            ON saved_reports(student_id, date_generated DESC);

            -- ============ LLM Usage Tracking ============

            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                question_type TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_llm_usage_student_time
            ON llm_usage(student_id, timestamp);
        ''')


def create_admin(username, password):
    """Create admin user if not exists."""
    with db_session() as conn:
        existing = conn.execute(
            "SELECT id FROM admin WHERE username = ?", (username,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO admin (username, password_hash) VALUES (?, ?)",
                (username, hash_password(password))
            )
            return True
        return False


def verify_admin(username, password):
    """Verify admin credentials."""
    with db_session() as conn:
        admin = conn.execute(
            "SELECT * FROM admin WHERE username = ?",
            (username,)
        ).fetchone()
        if not admin:
            return None

        is_valid, needs_rehash = verify_password(admin['password_hash'], password)
        if not is_valid:
            return None

        # Upgrade legacy hash to modern hash on successful login
        if needs_rehash:
            conn.execute(
                "UPDATE admin SET password_hash = ? WHERE id = ?",
                (hash_password(password), admin['id'])
            )

        return dict(admin)


def update_admin_password(admin_id, new_password):
    """Update an admin's password."""
    with db_session() as conn:
        conn.execute(
            "UPDATE admin SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), admin_id)
        )


def verify_student(username, password):
    """Verify student credentials."""
    with db_session() as conn:
        student = conn.execute(
            "SELECT * FROM student WHERE username = ?",
            (username,)
        ).fetchone()
        if not student:
            return None

        is_valid, needs_rehash = verify_password(student['password_hash'], password)
        if not is_valid:
            return None

        # Upgrade legacy hash to modern hash on successful login
        if needs_rehash:
            conn.execute(
                "UPDATE student SET password_hash = ? WHERE id = ?",
                (hash_password(password), student['id'])
            )

        return dict(student)


# ============ Class functions ============

def get_all_klassen():
    """Get all classes."""
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM klasse ORDER BY name").fetchall()
        result = [dict(r) for r in rows]
    return result


def create_klasse(name):
    """Create a new class."""
    with db_session() as conn:
        cursor = conn.execute("INSERT INTO klasse (name) VALUES (?)", (name,))
        return cursor.lastrowid


def delete_klasse(klasse_id):
    """Delete a class."""
    with db_session() as conn:
        conn.execute("DELETE FROM klasse WHERE id = ?", (klasse_id,))


def get_klasse(klasse_id):
    """Get a class by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
        result = dict(row) if row else None
    return result


# ============ Class Schedule functions ============

def get_class_schedule(klasse_id):
    """Get the scheduled weekday for a class."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM class_schedule WHERE klasse_id = ?",
            (klasse_id,)
        ).fetchone()
        return dict(row) if row else None


def set_class_schedule(klasse_id, weekday):
    """Set or update the scheduled weekday for a class (0=Monday, 6=Sunday)."""
    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO class_schedule (klasse_id, weekday) VALUES (?, ?)",
            (klasse_id, weekday)
        )


def delete_class_schedule(klasse_id):
    """Delete the schedule for a class."""
    with db_session() as conn:
        conn.execute("DELETE FROM class_schedule WHERE klasse_id = ?", (klasse_id,))


def get_next_class_date(klasse_id, current_date):
    """
    Calculate the next class date based on schedule.
    If schedule exists, finds next occurrence of scheduled weekday.
    Otherwise, adds 7 days.

    Args:
        klasse_id: ID of the class
        current_date: Current date as string (YYYY-MM-DD) or date object

    Returns:
        Next date as string (YYYY-MM-DD)
    """
    if isinstance(current_date, str):
        current = datetime.strptime(current_date, '%Y-%m-%d').date()
    else:
        current = current_date

    schedule = get_class_schedule(klasse_id)

    if schedule:
        # Find next occurrence of scheduled weekday
        target_weekday = schedule['weekday']  # 0=Monday, 6=Sunday
        current_weekday = current.weekday()   # 0=Monday, 6=Sunday

        # Calculate days to add (always move forward at least 1 day)
        days_ahead = (target_weekday - current_weekday) % 7
        if days_ahead == 0:
            days_ahead = 7  # If same weekday, jump to next week

        next_date = current + timedelta(days=days_ahead)
    else:
        # No schedule: just add 7 days
        next_date = current + timedelta(days=7)

    return next_date.isoformat()


def get_previous_class_date(klasse_id, current_date):
    """
    Calculate the previous class date based on schedule.
    If schedule exists, finds previous occurrence of scheduled weekday.
    Otherwise, subtracts 7 days.

    Args:
        klasse_id: ID of the class
        current_date: Current date as string (YYYY-MM-DD) or date object

    Returns:
        Previous date as string (YYYY-MM-DD)
    """
    if isinstance(current_date, str):
        current = datetime.strptime(current_date, '%Y-%m-%d').date()
    else:
        current = current_date

    schedule = get_class_schedule(klasse_id)

    if schedule:
        # Find previous occurrence of scheduled weekday
        target_weekday = schedule['weekday']  # 0=Monday, 6=Sunday
        current_weekday = current.weekday()   # 0=Monday, 6=Sunday

        # Calculate days to subtract (always move backward at least 1 day)
        days_back = (current_weekday - target_weekday) % 7
        if days_back == 0:
            days_back = 7  # If same weekday, jump to previous week

        previous_date = current - timedelta(days=days_back)
    else:
        # No schedule: just subtract 7 days
        previous_date = current - timedelta(days=7)

    return previous_date.isoformat()


# ============ Student functions ============

def get_existing_usernames():
    """Get all existing student usernames."""
    with db_session() as conn:
        rows = conn.execute("SELECT username FROM student").fetchall()
        return {r['username'] for r in rows}


def create_student(nachname, vorname, username, password):
    """Create a new student."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO student (nachname, vorname, username, password_hash) VALUES (?, ?, ?, ?)",
            (nachname, vorname, username, hash_password(password))
        )
        return cursor.lastrowid


def add_student_to_klasse(student_id, klasse_id):
    """Add student to a class."""
    with db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO student_klasse (student_id, klasse_id) VALUES (?, ?)",
            (student_id, klasse_id)
        )


def remove_student_from_klasse(student_id, klasse_id):
    """Remove student from a class."""
    with db_session() as conn:
        conn.execute(
            "DELETE FROM student_klasse WHERE student_id = ? AND klasse_id = ?",
            (student_id, klasse_id)
        )
        # Also remove their task assignment for this class
        conn.execute(
            "DELETE FROM student_task WHERE student_id = ? AND klasse_id = ?",
            (student_id, klasse_id)
        )


def move_student_to_klasse(student_id, from_klasse_id, to_klasse_id):
    """Move student from one class to another."""
    remove_student_from_klasse(student_id, from_klasse_id)
    add_student_to_klasse(student_id, to_klasse_id)


def delete_student(student_id):
    """Delete a student."""
    with db_session() as conn:
        conn.execute("DELETE FROM student WHERE id = ?", (student_id,))


def reset_student_password(student_id, new_password):
    """Reset a student's password."""
    with db_session() as conn:
        conn.execute(
            "UPDATE student SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), student_id)
        )


def get_students_in_klasse(klasse_id):
    """Get all students in a class with their active primary topic."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT s.*, st.task_id, t.name as task_name, st.abgeschlossen, st.manuell_abgeschlossen
            FROM student s
            JOIN student_klasse sk ON s.id = sk.student_id
            LEFT JOIN student_task st ON s.id = st.student_id AND st.klasse_id = ?
                AND st.abgeschlossen = 0 AND st.rolle = 'primary'
            LEFT JOIN task t ON st.task_id = t.id
            WHERE sk.klasse_id = ?
            ORDER BY s.nachname, s.vorname
        ''', (klasse_id, klasse_id)).fetchall()
        result = [dict(r) for r in rows]
    return result


def get_student(student_id):
    """Get a student by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM student WHERE id = ?", (student_id,)).fetchone()
        result = dict(row) if row else None
    return result


def update_student_setting(student_id, setting_name, value):
    """Update a student setting (UX Tier 1: Easy Reading Mode)."""
    with db_session() as conn:
        conn.execute(f"UPDATE student SET {setting_name} = ? WHERE id = ?", (value, student_id))


def get_student_klassen(student_id):
    """Get all classes a student belongs to."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT k.* FROM klasse k
            JOIN student_klasse sk ON k.id = sk.klasse_id
            WHERE sk.student_id = ?
            ORDER BY k.name
        ''', (student_id,)).fetchall()
        result = [dict(r) for r in rows]
    return result


def is_student_in_klasse(student_id, klasse_id):
    """Check if a student is in a specific class."""
    with db_session() as conn:
        row = conn.execute('''
            SELECT 1 FROM student_klasse
            WHERE student_id = ? AND klasse_id = ?
        ''', (student_id, klasse_id)).fetchone()
        return row is not None


def is_student_task_owner(student_id, student_task_id):
    """Check if a student_task belongs to the given student."""
    with db_session() as conn:
        row = conn.execute('''
            SELECT 1 FROM student_task
            WHERE id = ? AND student_id = ?
        ''', (student_task_id, student_id)).fetchone()
        return row is not None


# ============ Task functions ============

def get_all_tasks():
    """Get all tasks."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT * FROM task
            ORDER BY fach, stufe, number, name
        ''').fetchall()
        result = [dict(r) for r in rows]
    return result


def get_task(task_id):
    """Get a task by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def create_task(name, beschreibung, lernziel, fach, stufe, kategorie, quiz_json=None, number=0, why_learn_this=None, lernziel_schueler=None):
    """Create a new task."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO task (name, number, beschreibung, lernziel, lernziel_schueler, fach, stufe, kategorie, quiz_json, why_learn_this) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, number, beschreibung, lernziel, lernziel_schueler, fach, stufe, kategorie, quiz_json, why_learn_this)
        )
        return cursor.lastrowid


def update_task(task_id, name, beschreibung, lernziel, fach, stufe, kategorie, quiz_json=None, number=0, why_learn_this=None, subtask_quiz_required=None, lernziel_schueler=None):
    """Update a task."""
    with db_session() as conn:
        conn.execute('''
            UPDATE task SET name=?, number=?, beschreibung=?, lernziel=?, lernziel_schueler=?, fach=?, stufe=?,
            kategorie=?, quiz_json=?, why_learn_this=? WHERE id=?
        ''', (name, number, beschreibung, lernziel, lernziel_schueler, fach, stufe, kategorie, quiz_json, why_learn_this, task_id))
        if subtask_quiz_required is not None:
            conn.execute(
                "UPDATE task SET subtask_quiz_required = ? WHERE id = ?",
                (subtask_quiz_required, task_id)
            )


def delete_task(task_id):
    """Delete a task."""
    with db_session() as conn:
        conn.execute("DELETE FROM task WHERE id = ?", (task_id,))


# ============ Task Prerequisites ============

def get_task_voraussetzungen(task_id):
    """Get all prerequisites for a task."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT t.* FROM task t
            JOIN task_voraussetzung tv ON t.id = tv.voraussetzung_task_id
            WHERE tv.task_id = ?
            ORDER BY t.name
        ''', (task_id,)).fetchall()
        return [dict(r) for r in rows]


def add_task_voraussetzung(task_id, voraussetzung_task_id):
    """Add a prerequisite to a task."""
    with db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO task_voraussetzung (task_id, voraussetzung_task_id) VALUES (?, ?)",
            (task_id, voraussetzung_task_id)
        )


def remove_task_voraussetzung(task_id, voraussetzung_task_id):
    """Remove a prerequisite from a task."""
    with db_session() as conn:
        conn.execute(
            "DELETE FROM task_voraussetzung WHERE task_id = ? AND voraussetzung_task_id = ?",
            (task_id, voraussetzung_task_id)
        )


def set_task_voraussetzungen(task_id, voraussetzung_ids):
    """Set all prerequisites for a task (replaces existing)."""
    with db_session() as conn:
        conn.execute("DELETE FROM task_voraussetzung WHERE task_id = ?", (task_id,))
        for v_id in voraussetzung_ids:
            conn.execute(
                "INSERT INTO task_voraussetzung (task_id, voraussetzung_task_id) VALUES (?, ?)",
                (task_id, v_id)
            )


def check_voraussetzungen_erfuellt(student_id, klasse_id, task_id):
    """Check if student has completed all prerequisites for a task."""
    with db_session() as conn:
        # Get all prerequisites
        voraussetzungen = conn.execute(
            "SELECT voraussetzung_task_id FROM task_voraussetzung WHERE task_id = ?",
            (task_id,)
        ).fetchall()

        if not voraussetzungen:
            return True  # No prerequisites

        for v in voraussetzungen:
            # Check if student has completed this prerequisite
            completed = conn.execute('''
                SELECT abgeschlossen FROM student_task
                WHERE student_id = ? AND klasse_id = ? AND task_id = ? AND abgeschlossen = 1
            ''', (student_id, klasse_id, v['voraussetzung_task_id'])).fetchone()

            if not completed:
                return False

        return True


# ============ Task Export ============

def export_task_to_dict(task_id):
    """Export a single task with all related data as a dictionary.

    Returns a dict matching the import format from import_task.py, so that
    exported JSON can be edited and re-imported.

    Available helpers:
        get_task(task_id) -> dict with: name, number, beschreibung, lernziel,
                             fach, stufe, kategorie, quiz_json, why_learn_this
        get_subtasks(task_id) -> list of dicts with: beschreibung, reihenfolge,
                                 estimated_minutes
        get_materials(task_id) -> list of dicts with: typ, pfad, beschreibung
        get_task_voraussetzungen(task_id) -> list of task dicts (use their 'name')

    For quiz: task['quiz_json'] is a JSON string or None. Use json.loads() to parse.

    Return format (see import_task.py):
        {
            'name': ..., 'number': ..., 'beschreibung': ..., 'lernziel': ...,
            'fach': ..., 'stufe': ..., 'kategorie': ..., 'why_learn_this': ...,
            'subtasks': [{'beschreibung': ..., 'reihenfolge': ..., 'estimated_minutes': ...}],
            'materials': [{'typ': ..., 'pfad': ..., 'beschreibung': ...}],
            'quiz': {'questions': [...]} or None,
            'voraussetzungen': ['task_name_1', ...]
        }
    """
    task = get_task(task_id)
    if (task is None):
        return None
    else:

        subtasks = get_subtasks(task_id)
        materials = get_materials(task_id)
        task_voraussetzungen = get_task_voraussetzungen(task_id)
        material_assignments = get_material_subtask_assignments(task_id)

        # Build subtask ID -> reihenfolge lookup
        subtask_id_to_pos = {s['id']: s['reihenfolge'] for s in subtasks}

        subtasks_data = []
        for subtask in subtasks:
            st_data = {
                'beschreibung': subtask['beschreibung'],
                'reihenfolge': subtask['reihenfolge'],
                'estimated_minutes': subtask['estimated_minutes']
            }
            if subtask.get('quiz_json'):
                st_data['quiz'] = json.loads(subtask['quiz_json'])
            subtasks_data.append(st_data)

        materials_data = []
        for material in materials:
            mat_data = {
                'typ': material['typ'],
                'pfad': material['pfad'],
                'beschreibung': material['beschreibung']
            }
            # Include subtask_indices if material has specific assignments
            assigned_subtask_ids = material_assignments.get(material['id'])
            if assigned_subtask_ids:
                mat_data['subtask_indices'] = sorted(
                    subtask_id_to_pos[sid] for sid in assigned_subtask_ids
                    if sid in subtask_id_to_pos
                )
            materials_data.append(mat_data)
            
        if (task['quiz_json']):
            quiz_data = json.loads(task['quiz_json'])
        else:
            quiz_data = None
            
        if (task_voraussetzungen is not None):
            voraussetzungen_data = [v['name'] for v in task_voraussetzungen]
        else:
            voraussetzungen_data = []
                  
        data = {
            'name': task['name'],
            'number': task['number'],
            'beschreibung': task['beschreibung'],
            'lernziel': task['lernziel'],
            'lernziel_schueler': task.get('lernziel_schueler'),
            'fach': task['fach'],
            'stufe': task['stufe'],
            'kategorie': task['kategorie'],
            'why_learn_this': task['why_learn_this'],
            'subtask_quiz_required': bool(task.get('subtask_quiz_required', 1)),
            'subtasks': subtasks_data,
            'materials': materials_data,
            'quiz': quiz_data,
            'voraussetzungen': voraussetzungen_data
        }
        return data
          
        


def export_all_tasks():
    """Export all tasks. Wraps each task with export_task_to_dict()."""
    tasks = get_all_tasks()
    return [export_task_to_dict(t['id']) for t in tasks]


# ============ Wahlpflicht (Elective Groups) ============

def create_wahlpflicht_gruppe(name, beschreibung, fach, stufe):
    """Create an elective task group."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO wahlpflicht_gruppe (name, beschreibung, fach, stufe) VALUES (?, ?, ?, ?)",
            (name, beschreibung, fach, stufe)
        )
        return cursor.lastrowid


def get_wahlpflicht_gruppe(gruppe_id):
    """Get an elective group by ID."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM wahlpflicht_gruppe WHERE id = ?", (gruppe_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_wahlpflicht_gruppen():
    """Get all elective groups."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM wahlpflicht_gruppe ORDER BY fach, stufe, name"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_wahlpflicht_gruppe(gruppe_id):
    """Delete an elective group."""
    with db_session() as conn:
        conn.execute("DELETE FROM wahlpflicht_gruppe WHERE id = ?", (gruppe_id,))


def add_task_to_wahlpflicht(gruppe_id, task_id):
    """Add a task to an elective group."""
    with db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO wahlpflicht_task (gruppe_id, task_id) VALUES (?, ?)",
            (gruppe_id, task_id)
        )


def remove_task_from_wahlpflicht(gruppe_id, task_id):
    """Remove a task from an elective group."""
    with db_session() as conn:
        conn.execute(
            "DELETE FROM wahlpflicht_task WHERE gruppe_id = ? AND task_id = ?",
            (gruppe_id, task_id)
        )


def get_wahlpflicht_tasks(gruppe_id):
    """Get all tasks in an elective group."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT t.* FROM task t
            JOIN wahlpflicht_task wt ON t.id = wt.task_id
            WHERE wt.gruppe_id = ?
            ORDER BY t.name
        ''', (gruppe_id,)).fetchall()
        return [dict(r) for r in rows]


def check_wahlpflicht_erfuellt(student_id, klasse_id, gruppe_id):
    """Check if student has completed any task from an elective group."""
    with db_session() as conn:
        completed = conn.execute('''
            SELECT st.id FROM student_task st
            JOIN wahlpflicht_task wt ON st.task_id = wt.task_id
            WHERE st.student_id = ? AND st.klasse_id = ? AND wt.gruppe_id = ? AND st.abgeschlossen = 1
            LIMIT 1
        ''', (student_id, klasse_id, gruppe_id)).fetchone()
        return completed is not None


# ============ Subtask functions ============

def get_subtasks(task_id):
    """Get subtasks for a task."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM subtask WHERE task_id = ? ORDER BY reihenfolge",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def create_subtask(task_id, beschreibung, reihenfolge=0, estimated_minutes=None, quiz_json=None):
    """Create a subtask."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO subtask (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json) VALUES (?, ?, ?, ?, ?)",
            (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json)
        )
        return cursor.lastrowid


def delete_subtask(subtask_id):
    """Delete a subtask."""
    with db_session() as conn:
        conn.execute("DELETE FROM subtask WHERE id = ?", (subtask_id,))


def update_subtasks(task_id, subtasks_list, estimated_minutes_list=None, quiz_json_list=None):
    """Replace all subtasks for a task.

    Preserves visibility settings by matching subtask order/position.
    Orphans quiz_attempt records by setting subtask_id=NULL before deleting old subtasks.
    """
    with db_session() as conn:
        # Step 0: Orphan quiz_attempt subtask references before deleting subtasks
        old_subtask_ids = [r['id'] for r in conn.execute(
            "SELECT id FROM subtask WHERE task_id = ?", (task_id,)
        ).fetchall()]
        if old_subtask_ids:
            placeholders = ','.join('?' * len(old_subtask_ids))
            conn.execute(f"""
                UPDATE quiz_attempt SET subtask_id = NULL
                WHERE subtask_id IN ({placeholders})
            """, old_subtask_ids)

        # Step 1: Save visibility settings by order (reihenfolge), not ID
        old_visibility = conn.execute("""
            SELECT sv.klasse_id, sv.student_id, sv.enabled, sv.set_by_admin_id, s.reihenfolge
            FROM subtask_visibility sv
            JOIN subtask s ON sv.subtask_id = s.id
            WHERE s.task_id = ?
            ORDER BY s.reihenfolge
        """, (task_id,)).fetchall()

        # Convert to dict: (klasse_id or None, student_id or None, reihenfolge) -> (enabled, admin_id)
        visibility_by_position = {}
        for row in old_visibility:
            key = (row['klasse_id'], row['student_id'], row['reihenfolge'])
            visibility_by_position[key] = (row['enabled'], row['set_by_admin_id'])

        # Step 1b: Save material-subtask assignments by position
        old_mat_assignments = conn.execute("""
            SELECT ms.material_id, s.reihenfolge
            FROM material_subtask ms
            JOIN subtask s ON ms.subtask_id = s.id
            WHERE s.task_id = ?
        """, (task_id,)).fetchall()

        # {material_id: set(reihenfolge)}
        mat_assignments_by_position = {}
        for row in old_mat_assignments:
            mid = row['material_id']
            if mid not in mat_assignments_by_position:
                mat_assignments_by_position[mid] = set()
            mat_assignments_by_position[mid].add(row['reihenfolge'])

        # Step 2: Delete old visibility records, material assignments, and subtasks
        conn.execute("""
            DELETE FROM subtask_visibility
            WHERE subtask_id IN (SELECT id FROM subtask WHERE task_id = ?)
        """, (task_id,))
        conn.execute("""
            DELETE FROM material_subtask
            WHERE subtask_id IN (SELECT id FROM subtask WHERE task_id = ?)
        """, (task_id,))
        conn.execute("DELETE FROM subtask WHERE task_id = ?", (task_id,))

        # Step 3: Create new subtasks and track their IDs by position
        new_subtask_ids_by_position = {}

        for i, beschreibung in enumerate(subtasks_list):
            if beschreibung.strip():
                # Get estimated_minutes if provided
                estimated_minutes = None
                if estimated_minutes_list and i < len(estimated_minutes_list):
                    try:
                        minutes = estimated_minutes_list[i].strip()
                        estimated_minutes = int(minutes) if minutes else None
                    except (ValueError, AttributeError):
                        estimated_minutes = None

                # Get quiz_json if provided
                subtask_quiz = None
                if quiz_json_list and i < len(quiz_json_list):
                    qj = quiz_json_list[i].strip() if quiz_json_list[i] else ''
                    subtask_quiz = qj if qj else None

                cursor = conn.execute(
                    "INSERT INTO subtask (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json) VALUES (?, ?, ?, ?, ?)",
                    (task_id, beschreibung.strip(), i, estimated_minutes, subtask_quiz)
                )
                new_subtask_id = cursor.lastrowid
                new_subtask_ids_by_position[i] = new_subtask_id

        # Step 4: Restore visibility settings for matching positions
        for (klasse_id, student_id, old_position), (enabled, admin_id) in visibility_by_position.items():
            if old_position in new_subtask_ids_by_position:
                new_subtask_id = new_subtask_ids_by_position[old_position]
                conn.execute("""
                    INSERT INTO subtask_visibility (subtask_id, klasse_id, student_id, enabled, set_by_admin_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (new_subtask_id, klasse_id, student_id, enabled, admin_id))

        # Step 4b: Restore material-subtask assignments for matching positions
        for material_id, old_positions in mat_assignments_by_position.items():
            for old_pos in old_positions:
                if old_pos in new_subtask_ids_by_position:
                    conn.execute(
                        "INSERT INTO material_subtask (material_id, subtask_id) VALUES (?, ?)",
                        (material_id, new_subtask_ids_by_position[old_pos])
                    )



# ============ Material functions ============

def get_materials(task_id):
    """Get materials for a task."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM material WHERE task_id = ?",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_material(material_id):
    """Get a single material by ID."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM material WHERE id = ?",
            (material_id,)
        ).fetchone()
        return dict(row) if row else None


def create_material(task_id, typ, pfad, beschreibung=''):
    """Create a material."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO material (task_id, typ, pfad, beschreibung) VALUES (?, ?, ?, ?)",
            (task_id, typ, pfad, beschreibung)
        )
        return cursor.lastrowid


def delete_material(material_id):
    """Delete a material."""
    with db_session() as conn:
        conn.execute("DELETE FROM material WHERE id = ?", (material_id,))


def get_materials_for_subtask(task_id, subtask_id):
    """Get materials visible for a specific Aufgabe.

    A material is visible if:
    - It has NO rows in material_subtask (= visible everywhere, backward compatible)
    - OR it has a row linking it to this specific subtask
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT m.* FROM material m WHERE m.task_id = ?
            AND (
                NOT EXISTS (SELECT 1 FROM material_subtask ms WHERE ms.material_id = m.id)
                OR
                EXISTS (SELECT 1 FROM material_subtask ms WHERE ms.material_id = m.id AND ms.subtask_id = ?)
            )
        ''', (task_id, subtask_id)).fetchall()
        return [dict(r) for r in rows]


def get_material_subtask_assignments(task_id):
    """Get material-to-subtask assignments for a task.

    Returns: dict {material_id: set(subtask_ids)}
    Empty set = visible everywhere (no specific assignments).
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT ms.material_id, ms.subtask_id
            FROM material_subtask ms
            JOIN material m ON ms.material_id = m.id
            WHERE m.task_id = ?
        ''', (task_id,)).fetchall()

        assignments = {}
        for row in rows:
            mid = row['material_id']
            if mid not in assignments:
                assignments[mid] = set()
            assignments[mid].add(row['subtask_id'])
        return assignments


def set_material_subtask_assignments(material_id, subtask_ids):
    """Set which Aufgaben a material is assigned to.

    Empty list = visible everywhere (clears all assignments).
    """
    with db_session() as conn:
        conn.execute("DELETE FROM material_subtask WHERE material_id = ?", (material_id,))
        for sid in subtask_ids:
            conn.execute(
                "INSERT INTO material_subtask (material_id, subtask_id) VALUES (?, ?)",
                (material_id, sid)
            )


# ============ Student Task functions ============

def assign_task_to_student(student_id, klasse_id, task_id, rolle='primary'):
    """Assign a topic to a student in a class.

    History-preserving: completes existing active primary (if any) before inserting.
    No auto-visibility — learning paths handle which tasks are required/optional.

    Args:
        student_id: The student ID
        klasse_id: The class ID
        task_id: The task ID to assign
        rolle: 'primary' (main topic) or 'sidequest'
    """
    with db_session() as conn:
        # 1. Complete any existing active primary for this student+class
        if rolle == 'primary':
            conn.execute(
                "UPDATE student_task SET abgeschlossen = 1 WHERE student_id = ? AND klasse_id = ? AND abgeschlossen = 0 AND rolle = 'primary'",
                (student_id, klasse_id)
            )

        # 2. Skip if this exact topic is already active
        duplicate = conn.execute(
            "SELECT COUNT(*) as count FROM student_task WHERE student_id = ? AND klasse_id = ? AND task_id = ? AND rolle = ? AND abgeschlossen = 0",
            (student_id, klasse_id, task_id, rolle)
        ).fetchone()

        if duplicate['count'] >= 1:
            return

        # 3. Insert new assignment
        conn.execute(
            "INSERT INTO student_task (student_id, klasse_id, task_id, rolle, abgeschlossen, manuell_abgeschlossen) VALUES (?, ?, ?, ?, 0, 0)",
            (student_id, klasse_id, task_id, rolle)
        )
        

def assign_task_to_klasse(klasse_id, task_id, rolle='primary'):
    """Assign a topic to all students in a class.

    Delegates to assign_task_to_student() for each student (DRY).
    """
    with db_session() as conn:
        students = conn.execute(
            "SELECT student_id FROM student_klasse WHERE klasse_id = ?",
            (klasse_id,)
        ).fetchall()

    for s in students:
        assign_task_to_student(s['student_id'], klasse_id, task_id, rolle)


# ============================================================================
# Subtask Visibility Management
# ============================================================================

def get_visible_subtasks_for_student(student_id, klasse_id, task_id):
    """Get list of subtasks visible to a student based on visibility rules.

    Rules priority:
    1. Student-specific rules (if they exist)
    2. Class-wide rules (if no student rule exists)
    3. Default: NO subtasks visible (admin must explicitly enable)

    Args:
        student_id: The student ID
        klasse_id: The class ID the student is viewing the task in
        task_id: The task ID

    Returns:
        List of subtask dicts that are visible to this student
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT s.* FROM subtask s
            WHERE s.task_id = ?
            AND s.id IN (
                -- Student-specific rules (highest priority)
                SELECT sv.subtask_id FROM subtask_visibility sv
                WHERE sv.student_id = ? AND sv.enabled = 1

                UNION

                -- Class rules (if no student-specific rule exists)
                SELECT sv.subtask_id FROM subtask_visibility sv
                WHERE sv.klasse_id = ? AND sv.enabled = 1
                AND NOT EXISTS (
                    SELECT 1 FROM subtask_visibility sv2
                    WHERE sv2.subtask_id = sv.subtask_id
                    AND sv2.student_id = ?
                )
            )
            ORDER BY s.reihenfolge
        ''', (task_id, student_id, klasse_id, student_id)).fetchall()
        return [dict(r) for r in rows]


def get_subtask_visibility_settings(klasse_id=None, student_id=None, task_id=None):
    """Get current visibility settings for a context.

    Args:
        klasse_id: Optional class ID to filter by
        student_id: Optional student ID to filter by
        task_id: Optional task ID to filter by (gets subtasks for this task)

    Returns:
        Dict mapping subtask_id -> {'enabled': bool, 'source': 'class'|'student'}
    """
    with db_session() as conn:
        # Build query based on context
        conditions = []
        params = []

        if task_id:
            # Get all subtasks for this task first
            subtasks = conn.execute(
                'SELECT id FROM subtask WHERE task_id = ? ORDER BY reihenfolge',
                (task_id,)
            ).fetchall()
            subtask_ids = [s['id'] for s in subtasks]
        else:
            subtask_ids = None

        # Query visibility rules
        query = 'SELECT subtask_id, enabled, klasse_id, student_id FROM subtask_visibility WHERE 1=1'

        if klasse_id is not None:
            query += ' AND klasse_id = ?'
            params.append(klasse_id)

        if student_id is not None:
            query += ' AND student_id = ?'
            params.append(student_id)

        if subtask_ids:
            placeholders = ','.join('?' * len(subtask_ids))
            query += f' AND subtask_id IN ({placeholders})'
            params.extend(subtask_ids)

        rows = conn.execute(query, params).fetchall()

        # Build result mapping
        result = {}
        for r in rows:
            source = 'student' if r['student_id'] else 'class'
            result[r['subtask_id']] = {
                'enabled': bool(r['enabled']),
                'source': source
            }

        return result


def set_subtask_visibility_for_class(klasse_id, subtask_id, enabled, admin_id):
    """Set visibility of a subtask for an entire class.

    Args:
        klasse_id: The class ID
        subtask_id: The subtask ID
        enabled: True to enable, False to disable
        admin_id: Admin making the change (for audit trail)
    """
    with db_session() as conn:
        # Delete existing rule for this class+subtask
        conn.execute('''
            DELETE FROM subtask_visibility
            WHERE klasse_id = ? AND subtask_id = ?
        ''', (klasse_id, subtask_id))

        # Insert new rule
        conn.execute('''
            INSERT INTO subtask_visibility (subtask_id, klasse_id, enabled, set_by_admin_id)
            VALUES (?, ?, ?, ?)
        ''', (subtask_id, klasse_id, 1 if enabled else 0, admin_id))


def set_subtask_visibility_for_student(student_id, subtask_id, enabled, admin_id):
    """Set visibility of a subtask for an individual student.

    This creates a student-specific override that takes priority over class rules.

    Args:
        student_id: The student ID
        subtask_id: The subtask ID
        enabled: True to enable, False to disable
        admin_id: Admin making the change (for audit trail)
    """
    with db_session() as conn:
        # Delete existing rule for this student+subtask
        conn.execute('''
            DELETE FROM subtask_visibility
            WHERE student_id = ? AND subtask_id = ?
        ''', (student_id, subtask_id))

        # Insert new rule
        conn.execute('''
            INSERT INTO subtask_visibility (subtask_id, student_id, enabled, set_by_admin_id)
            VALUES (?, ?, ?, ?)
        ''', (subtask_id, student_id, 1 if enabled else 0, admin_id))


def clear_student_subtask_visibility_override(student_id, subtask_id):
    """Remove a student-specific visibility override, reverting to class default."""
    with db_session() as conn:
        conn.execute(
            'DELETE FROM subtask_visibility WHERE student_id = ? AND subtask_id = ?',
            (student_id, subtask_id)
        )


def bulk_set_subtask_visibility(klasse_id=None, student_id=None, subtask_ids=None, enabled=True, admin_id=None):
    """Bulk set visibility for multiple subtasks.

    Args:
        klasse_id: If set, applies to entire class
        student_id: If set, applies to individual student
        subtask_ids: List of subtask IDs to update
        enabled: True to enable, False to disable
        admin_id: Admin making the change
    """
    if not subtask_ids:
        return

    with db_session() as conn:
        for subtask_id in subtask_ids:
            if klasse_id:
                set_subtask_visibility_for_class(klasse_id, subtask_id, enabled, admin_id)
            elif student_id:
                set_subtask_visibility_for_student(student_id, subtask_id, enabled, admin_id)


def reset_subtask_visibility_to_class_default(student_id, task_id):
    """Remove all student-specific overrides for a task, reverting to class defaults.

    Args:
        student_id: The student ID
        task_id: The task ID
    """
    with db_session() as conn:
        # Get all subtasks for this task
        subtasks = conn.execute(
            'SELECT id FROM subtask WHERE task_id = ?',
            (task_id,)
        ).fetchall()

        # Delete student-specific rules
        for s in subtasks:
            conn.execute('''
                DELETE FROM subtask_visibility
                WHERE student_id = ? AND subtask_id = ?
            ''', (student_id, s['id']))


def get_student_task(student_id, klasse_id):
    """Get student's active primary topic for a class."""
    with db_session() as conn:
        row = conn.execute('''
            SELECT st.*, t.name, t.beschreibung, t.lernziel, t.fach, t.stufe, t.kategorie, t.quiz_json, t.why_learn_this, t.subtask_quiz_required
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.student_id = ? AND st.klasse_id = ?
              AND st.abgeschlossen = 0 AND st.rolle = 'primary'
            LIMIT 1
        ''', (student_id, klasse_id)).fetchone()
        result = dict(row) if row else None
    return result


def get_all_student_tasks(student_id, klasse_id):
    """Get all student_task rows (active + completed, all roles) for a class.

    Used by slug resolution — a student might view a completed topic's quiz results.
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT st.*, t.name, t.beschreibung, t.lernziel, t.fach, t.stufe, t.kategorie, t.quiz_json, t.why_learn_this, t.subtask_quiz_required
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.student_id = ? AND st.klasse_id = ?
            ORDER BY st.abgeschlossen ASC, st.id DESC
        ''', (student_id, klasse_id)).fetchall()
        result = [dict(r) for r in rows]
    return result


def get_student_subtask_progress(student_task_id):
    """Get subtask completion status for a student's task."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT sub.*, COALESCE(ss.erledigt, 0) as erledigt
            FROM subtask sub
            JOIN student_task st ON sub.task_id = st.task_id
            LEFT JOIN student_subtask ss ON sub.id = ss.subtask_id AND ss.student_task_id = ?
            WHERE st.id = ?
            ORDER BY sub.reihenfolge
        ''', (student_task_id, student_task_id)).fetchall()
        result = [dict(r) for r in rows]
    return result


def toggle_student_subtask(student_task_id, subtask_id, erledigt):
    """Toggle a subtask completion for a student.

    Returns dict with 'quiz_pending': True if a subtask quiz must be passed before advancing.
    """
    result = {'quiz_pending': False, 'subtask_id': subtask_id}
    with db_session() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO student_subtask (student_task_id, subtask_id, erledigt)
            VALUES (?, ?, ?)
        ''', (student_task_id, subtask_id, 1 if erledigt else 0))

        # If marking as complete, check if subtask has a quiz that blocks advancement
        if erledigt:
            subtask_row = conn.execute(
                "SELECT quiz_json FROM subtask WHERE id = ?", (subtask_id,)
            ).fetchone()
            st_row = conn.execute(
                "SELECT task_id FROM student_task WHERE id = ?", (student_task_id,)
            ).fetchone()
            task_row = conn.execute(
                "SELECT subtask_quiz_required FROM task WHERE id = ?", (st_row['task_id'],)
            ).fetchone() if st_row else None

            has_subtask_quiz = subtask_row and subtask_row['quiz_json']
            quiz_required = task_row and task_row['subtask_quiz_required']

            if has_subtask_quiz and quiz_required:
                # Check if quiz already passed
                quiz_passed = conn.execute('''
                    SELECT 1 FROM quiz_attempt
                    WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
                    LIMIT 1
                ''', (student_task_id, subtask_id)).fetchone()

                if not quiz_passed:
                    result['quiz_pending'] = True
                    return result

            _advance_to_next_subtask_internal(conn, student_task_id, subtask_id)

    return result



def _advance_to_next_subtask_internal(conn, student_task_id, current_subtask_id):
    """Check if all subtasks are complete and trigger task completion if so.

    A subtask is "incomplete" if: not erledigt, OR has a required quiz that hasn't been passed.
    Called after a subtask is completed or a quiz is passed.
    """
    st = conn.execute(
        "SELECT task_id FROM student_task WHERE id = ?",
        (student_task_id,)
    ).fetchone()

    if not st:
        return

    task_id = st['task_id']

    # Check if subtask quizzes are required for this task
    task_row = conn.execute(
        "SELECT subtask_quiz_required FROM task WHERE id = ?", (task_id,)
    ).fetchone()
    quiz_required = task_row and task_row['subtask_quiz_required']

    subtasks = conn.execute(
        "SELECT id, reihenfolge, quiz_json FROM subtask WHERE task_id = ? ORDER BY reihenfolge",
        (task_id,)
    ).fetchall()

    if not subtasks:
        return

    for sub in subtasks:
        subtask_id = sub['id']

        # Check if checkbox is ticked
        completed = conn.execute(
            "SELECT erledigt FROM student_subtask WHERE student_task_id = ? AND subtask_id = ?",
            (student_task_id, subtask_id)
        ).fetchone()

        if not completed or not completed['erledigt']:
            return  # Still incomplete

        # Checked off, but does it have a required quiz that hasn't been passed?
        if quiz_required and sub['quiz_json']:
            quiz_passed = conn.execute('''
                SELECT 1 FROM quiz_attempt
                WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
                LIMIT 1
            ''', (student_task_id, subtask_id)).fetchone()
            if not quiz_passed:
                return  # Quiz still pending

    # All subtasks truly complete — check task completion
    check_task_completion(student_task_id)


def advance_to_next_subtask(student_task_id, current_subtask_id):
    """Advance to the next incomplete subtask after completing the current one.

    Args:
        student_task_id: The student_task ID
        current_subtask_id: The subtask that was just completed
    """
    with db_session() as conn:
        _advance_to_next_subtask_internal(conn, student_task_id, current_subtask_id)



def mark_task_complete(student_task_id, manual=False):
    """Mark a task as complete."""
    with db_session() as conn:
        if manual:
            conn.execute(
                "UPDATE student_task SET abgeschlossen = 1, manuell_abgeschlossen = 1 WHERE id = ?",
                (student_task_id,)
            )
        else:
            conn.execute(
                "UPDATE student_task SET abgeschlossen = 1 WHERE id = ?",
                (student_task_id,)
            )


def check_task_completion(student_task_id):
    """Check if task should be marked complete.

    Complete = all visible subtasks erledigt + all required subtask quizzes passed
               + topic quiz passed (or no topic quiz).
    """
    with db_session() as conn:
        student_task_info = conn.execute('''
            SELECT student_id, klasse_id, task_id FROM student_task WHERE id = ?
        ''', (student_task_id,)).fetchone()

        if not student_task_info:
            return False

        student_id = student_task_info['student_id']
        klasse_id = student_task_info['klasse_id']
        task_id = student_task_info['task_id']

        # Get task settings
        task_info = conn.execute(
            "SELECT quiz_json, subtask_quiz_required FROM task WHERE id = ?", (task_id,)
        ).fetchone()

        # Q5A: Get visible subtasks for this student
        visible_subtasks = get_visible_subtasks_for_student(student_id, klasse_id, task_id)
        visible_subtask_ids = [s['id'] for s in visible_subtasks]

        if visible_subtask_ids:
            placeholders = ','.join('?' * len(visible_subtask_ids))
            subtask_rows = conn.execute(f'''
                SELECT sub.id, sub.quiz_json, COALESCE(ss.erledigt, 0) as erledigt
                FROM subtask sub
                LEFT JOIN student_subtask ss ON sub.id = ss.subtask_id AND ss.student_task_id = ?
                WHERE sub.id IN ({placeholders})
            ''', [student_task_id] + visible_subtask_ids).fetchall()

            quiz_required = task_info and task_info['subtask_quiz_required']

            for sub in subtask_rows:
                if not sub['erledigt']:
                    return False
                # Check subtask quiz if required
                if quiz_required and sub['quiz_json']:
                    quiz_passed = conn.execute('''
                        SELECT 1 FROM quiz_attempt
                        WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
                        LIMIT 1
                    ''', (student_task_id, sub['id'])).fetchone()
                    if not quiz_passed:
                        return False

        # Check topic-level quiz (filter: subtask_id IS NULL)
        has_topic_quiz = task_info and task_info['quiz_json']
        if has_topic_quiz:
            topic_quiz_passed = conn.execute('''
                SELECT 1 FROM quiz_attempt
                WHERE student_task_id = ? AND subtask_id IS NULL AND bestanden = 1
                LIMIT 1
            ''', (student_task_id,)).fetchone()

            if not topic_quiz_passed:
                # Check if quiz passed via game mode
                import json
                quiz = json.loads(task_info['quiz_json'])
                total_questions = len(quiz.get('questions', []))

                if total_questions > 0:
                    game_correct = conn.execute('''
                        SELECT COUNT(*) as count FROM game_task_progress
                        WHERE student_task_id = ? AND answered_correctly = 1
                    ''', (student_task_id,)).fetchone()

                    if game_correct['count'] < total_questions:
                        return False

        return True


# ============ Quiz functions ============

def save_quiz_attempt(student_task_id, punkte, max_punkte, antworten_json, subtask_id=None):
    """Save a quiz attempt. subtask_id=None means topic-level quiz."""
    # Pass threshold: floor(70%) of max points, minimum 1
    min_punkte = max(1, int(max_punkte * 0.7)) if max_punkte > 0 else 1
    bestanden = punkte >= min_punkte if max_punkte > 0 else False
    with db_session() as conn:
        cursor = conn.execute('''
            INSERT INTO quiz_attempt (student_task_id, subtask_id, punkte, max_punkte, bestanden, antworten_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (student_task_id, subtask_id, punkte, max_punkte, 1 if bestanden else 0, antworten_json))
        return cursor.lastrowid, bestanden


def get_quiz_attempts(student_task_id, subtask_id=None):
    """Get quiz attempts. subtask_id=None returns topic-level only; pass a value for subtask quiz."""
    with db_session() as conn:
        if subtask_id is not None:
            rows = conn.execute('''
                SELECT * FROM quiz_attempt WHERE student_task_id = ? AND subtask_id = ?
                ORDER BY timestamp DESC
            ''', (student_task_id, subtask_id)).fetchall()
        else:
            rows = conn.execute('''
                SELECT * FROM quiz_attempt WHERE student_task_id = ? AND subtask_id IS NULL
                ORDER BY timestamp DESC
            ''', (student_task_id,)).fetchall()
        return [dict(r) for r in rows]


def has_passed_subtask_quiz(student_task_id, subtask_id):
    """Returns True if any quiz_attempt for this student_task + subtask has bestanden=1."""
    with db_session() as conn:
        row = conn.execute('''
            SELECT 1 FROM quiz_attempt
            WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
            LIMIT 1
        ''', (student_task_id, subtask_id)).fetchone()
        return row is not None


def get_text_quiz_answers(klasse_id=None, only_fallback=False):
    """Get all text-based quiz answers (fill_blank, short_answer) for admin review.

    Returns flat list of dicts, one per text answer (not per attempt).
    Filters: klasse_id narrows to one class, only_fallback shows ungraded answers only.
    """
    with db_session() as conn:
        sql = '''
            SELECT qa.id as attempt_id, qa.timestamp, qa.antworten_json,
                   qa.subtask_id, qa.student_task_id,
                   s.vorname, s.nachname, s.id as student_id,
                   k.name as klasse_name, k.id as klasse_id,
                   t.name as task_name, t.quiz_json as task_quiz_json,
                   sub.beschreibung as subtask_name, sub.quiz_json as subtask_quiz_json
            FROM quiz_attempt qa
            JOIN student_task st ON qa.student_task_id = st.id
            JOIN student s ON st.student_id = s.id
            JOIN klasse k ON st.klasse_id = k.id
            JOIN task t ON st.task_id = t.id
            LEFT JOIN subtask sub ON qa.subtask_id = sub.id
            WHERE qa.antworten_json IS NOT NULL
        '''
        params = []
        if klasse_id:
            sql += ' AND k.id = ?'
            params.append(klasse_id)
        sql += ' ORDER BY qa.timestamp DESC LIMIT 500'

        rows = conn.execute(sql, params).fetchall()

    results = []
    for row in rows:
        row = dict(row)
        try:
            antworten = json.loads(row['antworten_json'])
        except (json.JSONDecodeError, TypeError):
            continue

        # Determine which quiz JSON to use for question lookup
        if row['subtask_id'] and row['subtask_quiz_json']:
            quiz_json_str = row['subtask_quiz_json']
        elif row['task_quiz_json']:
            quiz_json_str = row['task_quiz_json']
        else:
            quiz_json_str = None

        try:
            quiz = json.loads(quiz_json_str) if quiz_json_str else None
        except (json.JSONDecodeError, TypeError):
            quiz = None

        questions = quiz.get('questions', []) if quiz else []

        for q_idx_str, answer in antworten.items():
            # Skip MC answers (stored as lists)
            if not isinstance(answer, dict) or 'text' not in answer:
                continue

            source = answer.get('source', '')
            if only_fallback and source != 'fallback':
                continue

            # Look up question text by index
            try:
                q_idx = int(q_idx_str)
                question = questions[q_idx] if q_idx < len(questions) else None
            except (ValueError, IndexError):
                question = None

            question_text = question.get('text', '?') if question else '(Frage nicht mehr verfügbar)'
            question_type = question.get('type', 'fill_blank') if question else '?'

            results.append({
                'attempt_id': row['attempt_id'],
                'timestamp': row['timestamp'],
                'student_name': f"{row['vorname']} {row['nachname']}",
                'student_id': row['student_id'],
                'klasse_name': row['klasse_name'],
                'klasse_id': row['klasse_id'],
                'task_name': row['task_name'],
                'subtask_name': row['subtask_name'],
                'question_text': question_text,
                'question_type': question_type,
                'student_answer': answer.get('text', ''),
                'correct': answer.get('correct', False),
                'feedback': answer.get('feedback', ''),
                'source': source,
            })

    return results


# ============ Lesson functions ============

def create_or_get_unterricht(klasse_id, datum):
    """Create or get a lesson."""
    with db_session() as conn:
        existing = conn.execute(
            "SELECT id FROM unterricht WHERE klasse_id = ? AND datum = ?",
            (klasse_id, datum)
        ).fetchone()
        if existing:
            return existing['id']
        cursor = conn.execute(
            "INSERT INTO unterricht (klasse_id, datum) VALUES (?, ?)",
            (klasse_id, datum)
        )
        unterricht_id = cursor.lastrowid
        # Initialize all students in class with default values
        students = conn.execute(
            "SELECT student_id FROM student_klasse WHERE klasse_id = ?",
            (klasse_id,)
        ).fetchall()
        for s in students:
            conn.execute('''
                INSERT INTO unterricht_student (unterricht_id, student_id)
                VALUES (?, ?)
            ''', (unterricht_id, s['student_id']))
        return unterricht_id


def get_unterricht_students(unterricht_id):
    """Get all students with their evaluations for a lesson."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT us.*, s.nachname, s.vorname
            FROM unterricht_student us
            JOIN student s ON us.student_id = s.id
            ORDER BY s.nachname, s.vorname
        ''').fetchall()
        return [dict(r) for r in rows]


def get_klasse_unterricht(klasse_id):
    """Get all lessons for a class."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT * FROM unterricht WHERE klasse_id = ?
            ORDER BY datum DESC
        ''', (klasse_id,)).fetchall()
        return [dict(r) for r in rows]


def update_unterricht_student(unterricht_id, student_id, anwesend, admin_selbst, admin_respekt, admin_fortschritt, admin_kommentar, has_been_saved=1):
    """Update admin evaluation for a student in a lesson."""
    with db_session() as conn:
        conn.execute('''
            UPDATE unterricht_student SET
                anwesend = ?,
                admin_selbststaendigkeit = ?,
                admin_respekt = ?,
                admin_fortschritt = ?,
                admin_kommentar = ?,
                has_been_saved = ?
            WHERE unterricht_id = ? AND student_id = ?
        ''', (anwesend, admin_selbst, admin_respekt, admin_fortschritt, admin_kommentar, has_been_saved, unterricht_id, student_id))


def update_student_self_eval(unterricht_id, student_id, selbst_selbst, selbst_respekt):
    """Update student self-evaluation for a lesson."""
    with db_session() as conn:
        conn.execute('''
            UPDATE unterricht_student SET
                selbst_selbststaendigkeit = ?,
                selbst_respekt = ?
            WHERE unterricht_id = ? AND student_id = ?
        ''', (selbst_selbst, selbst_respekt, unterricht_id, student_id))


def get_student_unterricht(student_id, klasse_id):
    """Get lesson evaluations for a student in a class."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT us.*, u.datum
            FROM unterricht_student us
            JOIN unterricht u ON us.unterricht_id = u.id
            WHERE us.student_id = ? AND u.klasse_id = ?
            ORDER BY u.datum DESC
        ''', (student_id, klasse_id)).fetchall()
        return [dict(r) for r in rows]


# ============ Auto-Attendance from Login Data ============

def auto_fill_attendance(klasse_id, datum):
    """Auto-fill attendance by cross-referencing student logins with lesson date.

    Checks analytics_events for student login events on the given date.
    Only updates students where has_been_saved=0 (untouched defaults).
    Sets has_been_saved=2 to mark as auto-filled.

    Returns dict with counts: {present, absent, skipped}
    """
    unterricht_id = create_or_get_unterricht(klasse_id, datum)

    with db_session() as conn:
        # Get all students with untouched attendance (has_been_saved=0)
        unsaved = conn.execute('''
            SELECT us.student_id
            FROM unterricht_student us
            WHERE us.unterricht_id = ? AND us.has_been_saved = 0
        ''', (unterricht_id,)).fetchall()

        skipped = conn.execute('''
            SELECT COUNT(*) as cnt FROM unterricht_student
            WHERE unterricht_id = ? AND has_been_saved != 0
        ''', (unterricht_id,)).fetchone()['cnt']

        present = 0
        absent = 0

        for row in unsaved:
            student_id = row['student_id']

            # Check if student logged in on this date (school hours window)
            start = f"{datum} 07:30:00"
            end = f"{datum} 16:00:00"
            logged_in = conn.execute('''
                SELECT COUNT(*) as cnt FROM analytics_events
                WHERE user_id = ? AND user_type = 'student'
                  AND event_type = 'login'
                  AND timestamp BETWEEN ? AND ?
            ''', (student_id, start, end)).fetchone()['cnt'] > 0
                

            if logged_in:
                conn.execute('''
                    UPDATE unterricht_student
                    SET anwesend = 1, has_been_saved = 2
                    WHERE unterricht_id = ? AND student_id = ?
                ''', (unterricht_id, student_id))
                present += 1
            else:
                conn.execute('''
                    UPDATE unterricht_student
                    SET anwesend = 0,
                        admin_kommentar = ?,
                        has_been_saved = 2
                    WHERE unterricht_id = ? AND student_id = ?
                ''', (f'Automatisch: Keine Anmeldung am {datum}',
                      unterricht_id, student_id))
                absent += 1

    return {'present': present, 'absent': absent, 'skipped': skipped}


def auto_fill_all_scheduled_today():
    """Auto-fill attendance for all classes scheduled today.

    Queries class_schedule for today's weekday, then calls
    auto_fill_attendance() for each matching class.

    Returns list of dicts: [{klasse_id, klasse_name, present, absent, skipped}, ...]
    """
    today = datetime.now().date()
    today_weekday = today.weekday()  # 0=Monday, 6=Sunday
    datum = today.isoformat()

    with db_session() as conn:
        scheduled = conn.execute('''
            SELECT cs.klasse_id, k.name
            FROM class_schedule cs
            JOIN klasse k ON cs.klasse_id = k.id
            WHERE cs.weekday = ?
        ''', (today_weekday,)).fetchall()

    results = []
    for row in scheduled:
        counts = auto_fill_attendance(row['klasse_id'], datum)
        results.append({
            'klasse_id': row['klasse_id'],
            'klasse_name': row['name'],
            **counts
        })

    return results


# ============ Error Logging functions ============

def log_error(level, message, traceback=None, user_id=None, user_type=None, route=None, method=None, url=None):
    """Log an error to the database."""
    try:
        with db_session() as conn:
            conn.execute('''
                INSERT INTO error_log (level, message, traceback, user_id, user_type, route, method, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (level, message, traceback, user_id, user_type, route, method, url))
    except Exception as e:
        # If logging fails, print to stderr but don't crash
        print(f"ERROR: Failed to log error to database: {e}", file=sys.stderr)


def get_error_logs(limit=100, offset=0, level_filter=None):
    """Get error logs with pagination and optional filtering."""
    with db_session() as conn:
        query = "SELECT * FROM error_log"
        params = []

        if level_filter:
            query += " WHERE level = ?"
            params.append(level_filter)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_error_log_count(level_filter=None):
    """Get total count of error logs."""
    with db_session() as conn:
        if level_filter:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM error_log WHERE level = ?",
                (level_filter,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as count FROM error_log").fetchone()
        return row['count'] if row else 0


def get_error_log_stats():
    """Get error statistics (today, this week, by level)."""
    with db_session() as conn:
        # Count by level
        by_level = conn.execute('''
            SELECT level, COUNT(*) as count
            FROM error_log
            GROUP BY level
        ''').fetchall()

        # Count today (last 24 hours)
        today = conn.execute('''
            SELECT COUNT(*) as count FROM error_log
            WHERE timestamp >= datetime('now', '-1 day')
        ''').fetchone()

        # Count this week (last 7 days)
        week = conn.execute('''
            SELECT COUNT(*) as count FROM error_log
            WHERE timestamp >= datetime('now', '-7 days')
        ''').fetchone()

        return {
            'by_level': {row['level']: row['count'] for row in by_level},
            'today': today['count'] if today else 0,
            'week': week['count'] if week else 0
        }


def cleanup_old_error_logs(days=30):
    """Delete error logs older than specified days."""
    with db_session() as conn:
        cursor = conn.execute(
            "DELETE FROM error_log WHERE timestamp < datetime('now', ? || ' days')",
            (f'-{days}',)
        )
        return cursor.rowcount


def clear_all_error_logs():
    """Clear all error logs."""
    with db_session() as conn:
        cursor = conn.execute("DELETE FROM error_log")
        return cursor.rowcount


# ============ Analytics & Activity Logging functions ============

def log_analytics_event(event_type, user_id=None, user_type=None, metadata=None):
    """Log an analytics event asynchronously.

    Events are queued and written to the database by a background thread.
    This prevents blocking requests on slow disk I/O.

    Args:
        event_type: Type of event ('login', 'page_view', 'task_complete', etc.)
        user_id: ID of user performing action
        user_type: 'admin' or 'student'
        metadata: Dictionary of additional data (will be stored as JSON)
    """
    from analytics_queue import enqueue_event

    # Convert metadata to JSON if it's a dict
    metadata_json = json.dumps(metadata) if metadata else None

    # Enqueue event (non-blocking)
    enqueue_event(event_type, user_id, user_type, metadata_json)


def get_analytics_events(limit=100, offset=0, event_type=None, user_id=None, user_type=None, date_from=None, date_to=None):
    """Get analytics events with optional filtering.

    Args:
        limit: Maximum number of events to return
        offset: Number of events to skip (for pagination)
        event_type: Filter by event type
        user_id: Filter by user ID
        user_type: Filter by user type ('admin' or 'student')
        date_from: Filter events from this date (YYYY-MM-DD)
        date_to: Filter events until this date (YYYY-MM-DD)
    """
    with db_session() as conn:
        query = "SELECT * FROM analytics_events WHERE 1=1"
        params = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

        if user_type:
            query += " AND user_type = ?"
            params.append(user_type)

        if date_from:
            query += " AND date(timestamp) >= ?"
            params.append(date_from)

        if date_to:
            query += " AND date(timestamp) <= ?"
            params.append(date_to)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

        # Parse JSON metadata
        events = []
        for row in rows:
            event = dict(row)
            if event['metadata']:
                try:
                    event['metadata'] = json.loads(event['metadata'])
                except:
                    event['metadata'] = {}
            else:
                event['metadata'] = {}
            events.append(event)

        return events


def get_analytics_count(event_type=None, user_id=None, user_type=None, date_from=None, date_to=None):
    """Get count of analytics events with optional filtering."""
    with db_session() as conn:
        query = "SELECT COUNT(*) as count FROM analytics_events WHERE 1=1"
        params = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

        if user_type:
            query += " AND user_type = ?"
            params.append(user_type)

        if date_from:
            query += " AND date(timestamp) >= ?"
            params.append(date_from)

        if date_to:
            query += " AND date(timestamp) <= ?"
            params.append(date_to)

        row = conn.execute(query, params).fetchone()
        return row['count'] if row else 0


def get_analytics_overview():
    """Get overview statistics for analytics dashboard."""
    with db_session() as conn:
        # Active users today (unique users who logged in or had activity)
        active_today = conn.execute('''
            SELECT COUNT(DISTINCT user_id) as count
            FROM analytics_events
            WHERE date(timestamp) = date('now')
            AND user_id IS NOT NULL
        ''').fetchone()

        # Active users this week
        active_week = conn.execute('''
            SELECT COUNT(DISTINCT user_id) as count
            FROM analytics_events
            WHERE timestamp >= datetime('now', '-7 days')
            AND user_id IS NOT NULL
        ''').fetchone()

        # Page views today
        views_today = conn.execute('''
            SELECT COUNT(*) as count
            FROM analytics_events
            WHERE event_type = 'page_view'
            AND date(timestamp) = date('now')
        ''').fetchone()

        # Page views this week
        views_week = conn.execute('''
            SELECT COUNT(*) as count
            FROM analytics_events
            WHERE event_type = 'page_view'
            AND timestamp >= datetime('now', '-7 days')
        ''').fetchone()

        # Tasks completed today
        tasks_today = conn.execute('''
            SELECT COUNT(*) as count
            FROM analytics_events
            WHERE event_type = 'task_complete'
            AND date(timestamp) = date('now')
        ''').fetchone()

        # Tasks completed this week
        tasks_week = conn.execute('''
            SELECT COUNT(*) as count
            FROM analytics_events
            WHERE event_type = 'task_complete'
            AND timestamp >= datetime('now', '-7 days')
        ''').fetchone()

        # Logins today
        logins_today = conn.execute('''
            SELECT COUNT(*) as count
            FROM analytics_events
            WHERE event_type = 'login'
            AND date(timestamp) = date('now')
        ''').fetchone()

        # Event type breakdown
        by_type = conn.execute('''
            SELECT event_type, COUNT(*) as count
            FROM analytics_events
            WHERE timestamp >= datetime('now', '-7 days')
            GROUP BY event_type
            ORDER BY count DESC
        ''').fetchall()

        # Most active students this week
        active_students = conn.execute('''
            SELECT ae.user_id, s.vorname, s.nachname, COUNT(*) as event_count
            FROM analytics_events ae
            JOIN student s ON ae.user_id = s.id
            WHERE ae.user_type = 'student'
            AND ae.timestamp >= datetime('now', '-7 days')
            GROUP BY ae.user_id, s.vorname, s.nachname
            ORDER BY event_count DESC
            LIMIT 10
        ''').fetchall()

        # Popular routes this week
        popular_routes = conn.execute('''
            SELECT
                json_extract(metadata, '$.route') as route,
                COUNT(*) as count
            FROM analytics_events
            WHERE event_type = 'page_view'
            AND timestamp >= datetime('now', '-7 days')
            AND metadata IS NOT NULL
            GROUP BY route
            ORDER BY count DESC
            LIMIT 10
        ''').fetchall()

        return {
            'active_today': active_today['count'] if active_today else 0,
            'active_week': active_week['count'] if active_week else 0,
            'views_today': views_today['count'] if views_today else 0,
            'views_week': views_week['count'] if views_week else 0,
            'tasks_today': tasks_today['count'] if tasks_today else 0,
            'tasks_week': tasks_week['count'] if tasks_week else 0,
            'logins_today': logins_today['count'] if logins_today else 0,
            'by_type': {row['event_type']: row['count'] for row in by_type},
            'active_students': [dict(r) for r in active_students],
            'popular_routes': [dict(r) for r in popular_routes]
        }


def get_student_activity_log(student_id, limit=100, offset=0):
    """Get activity log for a specific student."""
    return get_analytics_events(
        limit=limit,
        offset=offset,
        user_id=student_id,
        user_type='student'
    )


def get_student_activity_summary(student_id, date_from=None, date_to=None):
    """Get activity summary for a student (for reports)."""
    with db_session() as conn:
        # Build date filter
        date_filter = "1=1"
        params = [student_id]

        if date_from:
            date_filter += " AND date(timestamp) >= ?"
            params.append(date_from)

        if date_to:
            date_filter += " AND date(timestamp) <= ?"
            params.append(date_to)

        # Count by event type
        event_counts = conn.execute(f'''
            SELECT event_type, COUNT(*) as count
            FROM analytics_events
            WHERE user_id = ? AND user_type = 'student'
            AND {date_filter}
            GROUP BY event_type
        ''', params).fetchall()

        # Unique login days
        login_days = conn.execute(f'''
            SELECT COUNT(DISTINCT date(timestamp)) as count
            FROM analytics_events
            WHERE user_id = ? AND user_type = 'student'
            AND event_type = 'login'
            AND {date_filter}
        ''', params).fetchone()

        # Tasks completed with details
        tasks_completed = conn.execute(f'''
            SELECT metadata, timestamp
            FROM analytics_events
            WHERE user_id = ? AND user_type = 'student'
            AND event_type = 'task_complete'
            AND {date_filter}
            ORDER BY timestamp DESC
        ''', params).fetchall()

        # Parse tasks
        tasks = []
        for row in tasks_completed:
            task_data = {'timestamp': row['timestamp']}
            if row['metadata']:
                try:
                    task_data.update(json.loads(row['metadata']))
                except:
                    pass
            tasks.append(task_data)

        return {
            'event_counts': {row['event_type']: row['count'] for row in event_counts},
            'login_days': login_days['count'] if login_days else 0,
            'tasks_completed': tasks
        }


def cleanup_old_analytics_events(days=210):
    """Delete analytics events older than specified days."""
    with db_session() as conn:
        cursor = conn.execute(
            "DELETE FROM analytics_events WHERE timestamp < datetime('now', ? || ' days')",
            (f'-{days}',)
        )
        return cursor.rowcount


def clear_all_analytics_events():
    """Clear all analytics events."""
    with db_session() as conn:
        cursor = conn.execute("DELETE FROM analytics_events")
        return cursor.rowcount


# ============ Saved Reports ============

def save_report_record(report_type, filename, klasse_id=None, student_id=None, date_from=None, date_to=None):
    """Save a record of a generated report."""
    with db_session() as conn:
        conn.execute(
            """INSERT INTO saved_reports (report_type, klasse_id, student_id, filename, date_from, date_to)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_type, klasse_id, student_id, filename, date_from, date_to)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_saved_reports(klasse_id=None, student_id=None, limit=20):
    """Get saved reports for a class or student."""
    with db_session() as conn:
        if klasse_id:
            rows = conn.execute(
                """SELECT id, report_type, date_generated, date_from, date_to, filename
                   FROM saved_reports
                   WHERE klasse_id = ?
                   ORDER BY date_generated DESC
                   LIMIT ?""",
                (klasse_id, limit)
            ).fetchall()
        elif student_id:
            rows = conn.execute(
                """SELECT id, report_type, date_generated, date_from, date_to, filename
                   FROM saved_reports
                   WHERE student_id = ?
                   ORDER BY date_generated DESC
                   LIMIT ?""",
                (student_id, limit)
            ).fetchall()
        else:
            return []
        return [dict(row) for row in rows]


def delete_old_saved_reports(days=365):
    """Delete saved report records older than specified days (files must be deleted separately)."""
    with db_session() as conn:
        cursor = conn.execute(
            "DELETE FROM saved_reports WHERE date_generated < datetime('now', ? || ' days')",
            (f'-{days}',)
        )
        return cursor.rowcount


def get_report_data_for_class(klasse_id, date_from=None, date_to=None):
    """Get all data needed for class report generation."""
    with db_session() as conn:
        # Get class info
        klasse = conn.execute(
            "SELECT id, name FROM klasse WHERE id = ?",
            (klasse_id,)
        ).fetchone()

        if not klasse:
            return None

        # Get all students in class with their task status
        students = get_students_in_klasse(klasse_id)

        # For each student, get activity summary and task progress
        student_data = []
        for student in students:
            summary = get_student_activity_summary(
                student['id'],
                date_from=date_from,
                date_to=date_to
            )

            # Get current task info
            current_task = get_student_task(student['id'], klasse_id)

            # Get last activity date
            last_activity = conn.execute(
                """SELECT MAX(timestamp) as last_seen
                   FROM analytics_events
                   WHERE user_id = ? AND user_type = 'student'""",
                (student['id'],)
            ).fetchone()

            # Compute task progress
            if current_task:
                task_name = current_task['name']
                # Get subtask progress
                subtasks = get_student_subtask_progress(current_task['id'])
                completed = sum(1 for s in subtasks if s['erledigt'])
                total = len(subtasks)

                # Get quiz status
                quiz_attempts = get_quiz_attempts(current_task['id'])
                quiz_passed = bool(quiz_attempts and quiz_attempts[-1]['bestanden']) if quiz_attempts else False

                # Check if task is completed
                is_completed = bool(current_task['abgeschlossen'])
            else:
                task_name = 'Keine Aufgabe'
                completed = 0
                total = 0
                quiz_passed = False
                is_completed = False

            student_data.append({
                'id': student['id'],
                'name': f"{student['nachname']}, {student['vorname']}",
                'username': student['username'],
                'task_name': task_name,
                'completed_subtasks': completed,
                'total_subtasks': total,
                'progress_percent': int((completed / total * 100) if total > 0 else 0),
                'quiz_passed': quiz_passed,
                'is_completed': is_completed,
                'login_days': summary['login_days'],
                'tasks_completed': summary['tasks_completed'],
                'last_activity': last_activity['last_seen'] if last_activity and last_activity['last_seen'] else None
            })

        return {
            'klasse': dict(klasse),
            'students': sorted(student_data, key=lambda x: x['name'])
        }


def get_report_data_for_student(student_id, report_type='summary', date_from=None, date_to=None):
    """Get all data needed for student report generation."""
    with db_session() as conn:
        # Get student info
        student = conn.execute(
            "SELECT id, username, vorname, nachname FROM student WHERE id = ?",
            (student_id,)
        ).fetchone()

        if not student:
            return None

        student_dict = dict(student)

        # Get student's classes
        klassen = conn.execute(
            """SELECT k.id, k.name
               FROM klasse k
               JOIN student_klasse sk ON k.id = sk.klasse_id
               WHERE sk.student_id = ?""",
            (student_id,)
        ).fetchall()

        # Get activity summary
        summary = get_student_activity_summary(
            student_id,
            date_from=date_from,
            date_to=date_to
        )

        # Get current tasks for all classes with computed progress
        current_tasks = []
        for klasse in klassen:
            task = get_student_task(student_id, klasse['id'])

            if task:
                # Compute progress from subtasks
                subtasks = get_student_subtask_progress(task['id'])
                completed = sum(1 for s in subtasks if s['erledigt'])
                total = len(subtasks)

                # Get quiz status
                quiz_attempts = get_quiz_attempts(task['id'])
                quiz_passed = bool(quiz_attempts and quiz_attempts[-1]['bestanden']) if quiz_attempts else False

                current_tasks.append({
                    'name': task['name'],
                    'klasse_name': klasse['name'],
                    'completed_subtasks': completed,
                    'total_subtasks': total,
                    'quiz_passed': quiz_passed,
                    'is_completed': bool(task['abgeschlossen'])
                })

        result = {
            'student': student_dict,
            'klassen': [dict(k) for k in klassen],
            'summary': summary,
            'current_tasks': current_tasks
        }

        # For complete report, add additional data
        if report_type == 'complete':
            # Get activity timeline (latest 100 events)
            result['activity_log'] = get_student_activity_log(
                student_id,
                limit=100
            )

            # Get attendance records
            result['attendance'] = conn.execute(
                """SELECT ut.datum as date, k.name as klasse_name, us.anwesend,
                          us.admin_selbststaendigkeit, us.admin_respekt,
                          us.admin_fortschritt, us.admin_kommentar
                   FROM unterricht_student us
                   JOIN unterricht ut ON us.unterricht_id = ut.id
                   JOIN klasse k ON ut.klasse_id = k.id
                   WHERE us.student_id = ?
                   ORDER BY ut.datum DESC
                   LIMIT 50""",
                (student_id,)
            ).fetchall()
            result['attendance'] = [dict(row) for row in result['attendance']]

            # Get quiz attempts (must join through student_task)
            result['quiz_attempts'] = conn.execute(
                """SELECT qa.timestamp, qa.punkte as score, qa.max_punkte as total_questions,
                          qa.bestanden as passed, t.name as task_name, k.name as klasse_name
                   FROM quiz_attempt qa
                   JOIN student_task st ON qa.student_task_id = st.id
                   JOIN task t ON st.task_id = t.id
                   JOIN klasse k ON st.klasse_id = k.id
                   WHERE st.student_id = ?
                   ORDER BY qa.timestamp DESC
                   LIMIT 20""",
                (student_id,)
            ).fetchall()
            result['quiz_attempts'] = [dict(row) for row in result['quiz_attempts']]

        return result


# ============ App Settings ============

def get_setting(key, default=None):
    """Get an application setting value.

    Args:
        key: Setting key name
        default: Default value if setting doesn't exist

    Returns:
        Setting value as string, or default if not found
    """
    with db_session() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,)
        ).fetchone()
        return row['value'] if row else default


def set_setting(key, value):
    """Set an application setting value.

    Args:
        key: Setting key name
        value: Setting value (will be converted to string)
    """
    with db_session() as conn:
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = CURRENT_TIMESTAMP""",
            (key, str(value))
        )


def get_bool_setting(key, default=False):
    """Get a boolean setting value.

    Args:
        key: Setting key name
        default: Default value if setting doesn't exist

    Returns:
        Boolean value
    """
    value = get_setting(key)
    if value is None:
        return default
    return value.lower() in ('true', '1', 'yes', 'on')


def set_bool_setting(key, value):
    """Set a boolean setting value.

    Args:
        key: Setting key name
        value: Boolean value
    """
    set_setting(key, 'true' if value else 'false')


# ============ LLM Usage Tracking ============

def check_llm_rate_limit(student_id):
    """Check if student is within their hourly LLM call limit.

    Returns True if calls are allowed, False if rate limit exceeded.
    """
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM llm_usage WHERE student_id = ? AND timestamp > datetime('now', '-1 hour')",
            (student_id,)
        ).fetchone()
        return row['cnt'] < config.LLM_MAX_CALLS_PER_STUDENT_PER_HOUR


def record_llm_usage(student_id, question_type, tokens_used=0):
    """Record an LLM API call for rate limiting and monitoring."""
    with db_session() as conn:
        conn.execute(
            "INSERT INTO llm_usage (student_id, question_type, tokens_used) VALUES (?, ?, ?)",
            (student_id, question_type, tokens_used)
        )
