import json
import os
import sys
from hashlib import sha256
from contextlib import contextmanager
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import config

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
    """Get database connection."""
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    if USE_SQLCIPHER and SQLCIPHER_KEY:
        # Set encryption key - escape any double quotes in key
        safe_key = SQLCIPHER_KEY.replace('"', '""')
        conn.execute(f'PRAGMA key = "{safe_key}"')
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
                password_hash TEXT NOT NULL
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
                fach TEXT NOT NULL,
                stufe TEXT NOT NULL,
                kategorie TEXT NOT NULL DEFAULT 'pflicht',  -- pflicht/bonus
                quiz_json TEXT  -- JSON format for quiz questions
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

            -- Student task assignment (per class)
            CREATE TABLE IF NOT EXISTS student_task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                klasse_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                abgeschlossen INTEGER NOT NULL DEFAULT 0,
                manuell_abgeschlossen INTEGER NOT NULL DEFAULT 0,
                UNIQUE(student_id, klasse_id),
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
                punkte INTEGER NOT NULL,
                max_punkte INTEGER NOT NULL,
                bestanden INTEGER NOT NULL,
                antworten_json TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_task_id) REFERENCES student_task(id) ON DELETE CASCADE
            );

            -- Lessons (Unterricht)
            CREATE TABLE IF NOT EXISTS unterricht (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                klasse_id INTEGER NOT NULL,
                datum DATE NOT NULL,
                UNIQUE(klasse_id, datum),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE
            );

            -- Lesson attendance and evaluation
            CREATE TABLE IF NOT EXISTS unterricht_student (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unterricht_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                anwesend INTEGER NOT NULL DEFAULT 1,
                -- Admin evaluation
                admin_selbststaendigkeit INTEGER DEFAULT 2,
                admin_respekt INTEGER DEFAULT 2,
                admin_fortschritt INTEGER DEFAULT 2,
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
        return [dict(r) for r in rows]


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
        return dict(row) if row else None


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
    """Get all students in a class."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT s.*, st.task_id, t.name as task_name, st.abgeschlossen, st.manuell_abgeschlossen
            FROM student s
            JOIN student_klasse sk ON s.id = sk.student_id
            LEFT JOIN student_task st ON s.id = st.student_id AND st.klasse_id = ?
            LEFT JOIN task t ON st.task_id = t.id
            WHERE sk.klasse_id = ?
            ORDER BY s.nachname, s.vorname
        ''', (klasse_id, klasse_id)).fetchall()
        return [dict(r) for r in rows]


def get_student(student_id):
    """Get a student by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM student WHERE id = ?", (student_id,)).fetchone()
        return dict(row) if row else None


def get_student_klassen(student_id):
    """Get all classes a student belongs to."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT k.* FROM klasse k
            JOIN student_klasse sk ON k.id = sk.klasse_id
            WHERE sk.student_id = ?
            ORDER BY k.name
        ''', (student_id,)).fetchall()
        return [dict(r) for r in rows]


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
        return [dict(r) for r in rows]


def get_task(task_id):
    """Get a task by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def create_task(name, beschreibung, lernziel, fach, stufe, kategorie, quiz_json=None, number=0):
    """Create a new task."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO task (name, number, beschreibung, lernziel, fach, stufe, kategorie, quiz_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, number, beschreibung, lernziel, fach, stufe, kategorie, quiz_json)
        )
        return cursor.lastrowid


def update_task(task_id, name, beschreibung, lernziel, fach, stufe, kategorie, quiz_json=None, number=0):
    """Update a task."""
    with db_session() as conn:
        conn.execute('''
            UPDATE task SET name=?, number=?, beschreibung=?, lernziel=?, fach=?, stufe=?,
            kategorie=?, quiz_json=? WHERE id=?
        ''', (name, number, beschreibung, lernziel, fach, stufe, kategorie, quiz_json, task_id))


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


def create_subtask(task_id, beschreibung, reihenfolge=0):
    """Create a subtask."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO subtask (task_id, beschreibung, reihenfolge) VALUES (?, ?, ?)",
            (task_id, beschreibung, reihenfolge)
        )
        return cursor.lastrowid


def delete_subtask(subtask_id):
    """Delete a subtask."""
    with db_session() as conn:
        conn.execute("DELETE FROM subtask WHERE id = ?", (subtask_id,))


def update_subtasks(task_id, subtasks_list):
    """Replace all subtasks for a task."""
    with db_session() as conn:
        conn.execute("DELETE FROM subtask WHERE task_id = ?", (task_id,))
        for i, beschreibung in enumerate(subtasks_list):
            if beschreibung.strip():
                conn.execute(
                    "INSERT INTO subtask (task_id, beschreibung, reihenfolge) VALUES (?, ?, ?)",
                    (task_id, beschreibung.strip(), i)
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


# ============ Student Task functions ============

def assign_task_to_student(student_id, klasse_id, task_id):
    """Assign a task to a student in a class."""
    with db_session() as conn:
        # Use INSERT OR REPLACE to update existing assignment
        conn.execute('''
            INSERT OR REPLACE INTO student_task (student_id, klasse_id, task_id, abgeschlossen, manuell_abgeschlossen)
            VALUES (?, ?, ?, 0, 0)
        ''', (student_id, klasse_id, task_id))


def assign_task_to_klasse(klasse_id, task_id):
    """Assign a task to all students in a class."""
    with db_session() as conn:
        students = conn.execute(
            "SELECT student_id FROM student_klasse WHERE klasse_id = ?",
            (klasse_id,)
        ).fetchall()
        for s in students:
            conn.execute('''
                INSERT OR REPLACE INTO student_task (student_id, klasse_id, task_id, abgeschlossen, manuell_abgeschlossen)
                VALUES (?, ?, ?, 0, 0)
            ''', (s['student_id'], klasse_id, task_id))


def get_student_task(student_id, klasse_id):
    """Get student's current task for a class."""
    with db_session() as conn:
        row = conn.execute('''
            SELECT st.*, t.name, t.beschreibung, t.lernziel, t.fach, t.stufe, t.kategorie, t.quiz_json
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.student_id = ? AND st.klasse_id = ?
        ''', (student_id, klasse_id)).fetchone()
        return dict(row) if row else None


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
        return [dict(r) for r in rows]


def toggle_student_subtask(student_task_id, subtask_id, erledigt):
    """Toggle a subtask completion for a student."""
    with db_session() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO student_subtask (student_task_id, subtask_id, erledigt)
            VALUES (?, ?, ?)
        ''', (student_task_id, subtask_id, 1 if erledigt else 0))


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
    """Check if task should be marked complete (all subtasks + quiz passed via traditional or game mode)."""
    with db_session() as conn:
        # Check all subtasks completed
        subtasks = conn.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN COALESCE(ss.erledigt, 0) = 1 THEN 1 ELSE 0 END) as completed
            FROM subtask sub
            JOIN student_task st ON sub.task_id = st.task_id
            LEFT JOIN student_subtask ss ON sub.id = ss.subtask_id AND ss.student_task_id = ?
            WHERE st.id = ?
        ''', (student_task_id, student_task_id)).fetchone()

        if subtasks['total'] > 0 and subtasks['total'] != subtasks['completed']:
            return False

        # Check quiz passed (traditional method)
        quiz_passed = conn.execute('''
            SELECT bestanden FROM quiz_attempt
            WHERE student_task_id = ? AND bestanden = 1
            LIMIT 1
        ''', (student_task_id,)).fetchone()

        # Get task to check if it has a quiz
        task_info = conn.execute('''
            SELECT t.quiz_json, st.student_id FROM task t
            JOIN student_task st ON t.id = st.task_id
            WHERE st.id = ?
        ''', (student_task_id,)).fetchone()

        has_quiz = task_info and task_info['quiz_json']

        if has_quiz and not quiz_passed:
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

def save_quiz_attempt(student_task_id, punkte, max_punkte, antworten_json):
    """Save a quiz attempt."""
    bestanden = (punkte / max_punkte) >= 0.8 if max_punkte > 0 else False
    with db_session() as conn:
        cursor = conn.execute('''
            INSERT INTO quiz_attempt (student_task_id, punkte, max_punkte, bestanden, antworten_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (student_task_id, punkte, max_punkte, 1 if bestanden else 0, antworten_json))
        return cursor.lastrowid, bestanden


def get_quiz_attempts(student_task_id):
    """Get all quiz attempts for a student task."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT * FROM quiz_attempt WHERE student_task_id = ?
            ORDER BY timestamp DESC
        ''', (student_task_id,)).fetchall()
        return [dict(r) for r in rows]


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
    """Log an analytics event.

    Args:
        event_type: Type of event ('login', 'page_view', 'task_complete', etc.)
        user_id: ID of user performing action
        user_type: 'admin' or 'student'
        metadata: Dictionary of additional data (will be stored as JSON)
    """
    try:
        metadata_json = json.dumps(metadata) if metadata else None
        with db_session() as conn:
            conn.execute('''
                INSERT INTO analytics_events (event_type, user_id, user_type, metadata)
                VALUES (?, ?, ?, ?)
            ''', (event_type, user_id, user_type, metadata_json))
    except Exception as e:
        # If logging fails, print to stderr but don't crash
        print(f"ERROR: Failed to log analytics event: {e}", file=sys.stderr)


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
