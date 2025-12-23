import sqlite3
import json
from hashlib import sha256
from contextlib import contextmanager
import config


def hash_password(password):
    """Simple password hashing."""
    return sha256(password.encode()).hexdigest()


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
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
                password_plain TEXT  -- Stored for admin to view, remove in production
            );

            -- Student-Class relationship (many-to-many)
            CREATE TABLE IF NOT EXISTS student_klasse (
                student_id INTEGER NOT NULL,
                klasse_id INTEGER NOT NULL,
                PRIMARY KEY (student_id, klasse_id),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE
            );

            -- Tasks (Aufgaben)
            CREATE TABLE IF NOT EXISTS task (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                beschreibung TEXT,
                lernziel TEXT,
                fach TEXT NOT NULL,
                stufe TEXT NOT NULL,
                kategorie TEXT NOT NULL DEFAULT 'pflicht',  -- pflicht/bonus
                voraussetzung_id INTEGER,
                quiz_json TEXT,  -- JSON format for quiz questions
                FOREIGN KEY (voraussetzung_id) REFERENCES task(id) ON DELETE SET NULL
            );

            -- Follow-up tasks (Folgeaufgaben)
            CREATE TABLE IF NOT EXISTS task_folge (
                task_id INTEGER NOT NULL,
                folge_task_id INTEGER NOT NULL,
                PRIMARY KEY (task_id, folge_task_id),
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
                FOREIGN KEY (folge_task_id) REFERENCES task(id) ON DELETE CASCADE
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
            "SELECT * FROM admin WHERE username = ? AND password_hash = ?",
            (username, hash_password(password))
        ).fetchone()
        return dict(admin) if admin else None


def verify_student(username, password):
    """Verify student credentials."""
    with db_session() as conn:
        student = conn.execute(
            "SELECT * FROM student WHERE username = ? AND password_hash = ?",
            (username, hash_password(password))
        ).fetchone()
        return dict(student) if student else None


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
            "INSERT INTO student (nachname, vorname, username, password_hash, password_plain) VALUES (?, ?, ?, ?, ?)",
            (nachname, vorname, username, hash_password(password), password)
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


# ============ Task functions ============

def get_all_tasks():
    """Get all tasks."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT t.*, p.name as voraussetzung_name
            FROM task t
            LEFT JOIN task p ON t.voraussetzung_id = p.id
            ORDER BY t.fach, t.stufe, t.name
        ''').fetchall()
        return [dict(r) for r in rows]


def get_task(task_id):
    """Get a task by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def create_task(name, beschreibung, lernziel, fach, stufe, kategorie, voraussetzung_id=None, quiz_json=None):
    """Create a new task."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO task (name, beschreibung, lernziel, fach, stufe, kategorie, voraussetzung_id, quiz_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, beschreibung, lernziel, fach, stufe, kategorie, voraussetzung_id, quiz_json)
        )
        return cursor.lastrowid


def update_task(task_id, name, beschreibung, lernziel, fach, stufe, kategorie, voraussetzung_id=None, quiz_json=None):
    """Update a task."""
    with db_session() as conn:
        conn.execute('''
            UPDATE task SET name=?, beschreibung=?, lernziel=?, fach=?, stufe=?,
            kategorie=?, voraussetzung_id=?, quiz_json=? WHERE id=?
        ''', (name, beschreibung, lernziel, fach, stufe, kategorie, voraussetzung_id, quiz_json, task_id))


def delete_task(task_id):
    """Delete a task."""
    with db_session() as conn:
        conn.execute("DELETE FROM task WHERE id = ?", (task_id,))


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


def update_unterricht_student(unterricht_id, student_id, anwesend, admin_selbst, admin_respekt, admin_fortschritt, admin_kommentar):
    """Update admin evaluation for a student in a lesson."""
    with db_session() as conn:
        conn.execute('''
            UPDATE unterricht_student SET
                anwesend = ?,
                admin_selbststaendigkeit = ?,
                admin_respekt = ?,
                admin_fortschritt = ?,
                admin_kommentar = ?
            WHERE unterricht_id = ? AND student_id = ?
        ''', (anwesend, admin_selbst, admin_respekt, admin_fortschritt, admin_kommentar, unterricht_id, student_id))


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
