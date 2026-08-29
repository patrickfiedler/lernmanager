import json
import os
import re
import sys
from hashlib import sha256
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import urlparse
import urllib.request
import urllib.error
from werkzeug.security import generate_password_hash, check_password_hash
import config

# Terminology mapping (UI German → Database English):
#   Thema (topic)       → task table
#   Aufgabe (task)      → subtask table
#   Schüler-Thema       → student_task table

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


def now_local(fmt='%Y-%m-%d %H:%M:%S'):
    """Current wall-clock time in config.TIMEZONE, as a string for the DB.

    Every timestamp this app stores goes through here. SQLite's CURRENT_TIMESTAMP
    is UTC unconditionally, so mixing it with Python's local-time writes left the
    DB holding two different time bases and the UI showing rows two hours early.

    Deliberately not datetime.now(): that reads the server's TZ env var, and a VPS
    rebuilt without one silently reintroduces the bug. ZoneInfo also gets DST right,
    which a fixed offset would not.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(config.TIMEZONE)).strftime(fmt)
    except Exception:
        # Unknown zone name or missing tzdata -- a wrong-by-an-hour timestamp beats
        # a 500 on every write path that logs anything.
        return datetime.now().strftime(fmt)


def local_cutoff(**delta):
    """A past instant on the same basis as now_local(), for time-window queries.

    Comparisons must use the same clock the rows were written with; SQL-side
    datetime('now') is UTC and would silently drift against local-time rows.
    """
    try:
        from zoneinfo import ZoneInfo
        base = datetime.now(ZoneInfo(config.TIMEZONE))
    except Exception:
        base = datetime.now()
    return (base - timedelta(**delta)).strftime('%Y-%m-%d %H:%M:%S')


def get_db():
    """Get database connection with optimized performance settings."""
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
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
                name TEXT NOT NULL,
                llm_artifact_feedback_enabled INTEGER NOT NULL DEFAULT 0,
                llm_transparency_mode INTEGER DEFAULT NULL,
                artifact_gate_required INTEGER NOT NULL DEFAULT 1,
                klassenstufe INTEGER DEFAULT NULL,
                kurs_code TEXT DEFAULT NULL,
                show_completed_topics INTEGER NOT NULL DEFAULT 0
            );

            -- Students (Schüler)
            CREATE TABLE IF NOT EXISTS student (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nachname TEXT NOT NULL,
                vorname TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                lernpfad TEXT DEFAULT 'bergweg',  -- wanderweg/bergweg/gipfeltour/seilbahn
                easy_reading_mode INTEGER DEFAULT 0,
                llm_transparency_mode INTEGER DEFAULT 0,
                netzwerk_id TEXT  -- surname.firstname school network ID, matches scan-folders' folder names (grading-service-deployment.md §Phase 2)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_student_netzwerk_id ON student(netzwerk_id) WHERE netzwerk_id IS NOT NULL;

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
                subtask_quiz_required INTEGER DEFAULT 1,  -- 1=must pass subtask quizzes, 0=optional
                module_tier TEXT NOT NULL DEFAULT 'kern_standard',  -- kern_standard/hero (Chemie swap-rule tier)
                unit_slug TEXT,  -- stable author-chosen ID (e.g. "modul_01"), referenced by other units' connections.building_on
                connections_json TEXT  -- JSON: {building_on: [...], arriving_at: [...]} (Clayden-style unit connections)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_task_unit_slug ON task(unit_slug) WHERE unit_slug IS NOT NULL;

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

            -- Sub-tasks (Teilaufgaben)
            CREATE TABLE IF NOT EXISTS subtask (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                beschreibung TEXT NOT NULL,
                reihenfolge INTEGER NOT NULL DEFAULT 0,
                estimated_minutes INTEGER,
                quiz_json TEXT,  -- per-subtask quiz JSON
                path TEXT,  -- wanderweg/bergweg/gipfeltour/seilbahn (lowest path that includes this task)
                path_model TEXT DEFAULT 'skip',  -- skip: lower paths skip; depth: all paths do it
                graded_artifact_json TEXT,  -- JSON: {keyword, format, rubric}
                artifact_gate_json TEXT,  -- JSON: deterministic gate config (no LLM)
                hidden INTEGER DEFAULT 0,  -- 1=hidden from all students (admin override)
                fertig_wenn TEXT,
                tipps TEXT,
                checkpoint_type TEXT,  -- quiz/abnahme/artefakt (Chemie Checkpoint-Punktekonto; NULL = not a checkpoint)
                kern_standard_tag TEXT,  -- kern/standard (NULL = not a checkpoint)
                checkpoint_hints_json TEXT,  -- JSON array of escalating Tipp-button hints (quiz checkpoints)
                school_only INTEGER NOT NULL DEFAULT 0,  -- 1=Quiz-Checkpoint only accessible from school network
                fork_group TEXT,  -- groups subtasks (across branches) into one fork/choice decision point
                fork_branch TEXT,  -- which branch within fork_group this subtask belongs to (e.g. 'a', 'b', 'c')
                fork_branch_label TEXT,  -- student-facing branch name, set once on branch's first subtask
                fork_branch_note TEXT,  -- optional steering note shown on the selection screen
                fork_required INTEGER NOT NULL DEFAULT 1,  -- 0=enrichment fork (unpicked branches stay as Zusatz)
                is_intro INTEGER NOT NULL DEFAULT 0,  -- 1=Einführung subtask, excluded from progress-count denominator
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Materials (Materialien)
            CREATE TABLE IF NOT EXISTS material (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                typ TEXT NOT NULL,  -- 'link' or 'datei'
                pfad TEXT NOT NULL,  -- URL or file path
                beschreibung TEXT,
                attribution TEXT,  -- photographer/source credit
                school_only INTEGER NOT NULL DEFAULT 0,  -- 1=only downloadable from school network (network gate)
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
                practice_unlocked INTEGER DEFAULT 0,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (klasse_id) REFERENCES klasse(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
            );

            -- Practice questions unlocked for a whole class (per topic)
            CREATE TABLE IF NOT EXISTS class_practice_unlock (
                klasse_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                PRIMARY KEY (klasse_id, task_id)
            );

            -- Student sub-task completion
            CREATE TABLE IF NOT EXISTS student_subtask (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_task_id INTEGER NOT NULL,
                subtask_id INTEGER NOT NULL,
                erledigt INTEGER NOT NULL DEFAULT 0,
                completed_at DATETIME,
                artifact_gate_passed INTEGER DEFAULT NULL,
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
                quiz_snapshot_json TEXT,
                timestamp DATETIME DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (student_task_id) REFERENCES student_task(id) ON DELETE CASCADE
            );

            -- Checkpoint-Punktekonto attempt log (Chemie 11/12 grading model)
            -- One row per completed checkpoint, not per submission (retries live in
            -- attempt_count/hint_count). See docs/shared/lernmanager/chemie-data-contract.md
            -- checkpoint_id deliberately carries no FK constraint (unlike student_id/
            -- module_id): deleting/editing away an Aufgabe must not cascade-delete a
            -- student's graded checkpoint history (migrate_047). quiz_snapshot_json
            -- is what keeps the row readable once that Aufgabe is gone.
            CREATE TABLE IF NOT EXISTS checkpoint_attempt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                checkpoint_id INTEGER NOT NULL,  -- = subtask.id, no FK -- see above
                module_id INTEGER NOT NULL,  -- = task.id
                checkpoint_type TEXT NOT NULL,  -- quiz/abnahme/artefakt
                kern_standard_tag TEXT NOT NULL,  -- kern/standard
                score INTEGER NOT NULL,  -- fixed scale: 0/2/3
                attempt_count INTEGER NOT NULL DEFAULT 1,
                hint_count INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                needs_review INTEGER NOT NULL DEFAULT 0,  -- 1 = a question's score is a give-up forced by LLM grading being unavailable, not a real give-up -- teacher should re-grade by hand
                review_notes TEXT,  -- JSON: {"questions": [question_index, ...]} that need manual re-grading
                quiz_snapshot_json TEXT,  -- quiz_json as it was at completion time (content can be edited later)
                superseded_at TEXT,  -- set instead of deleting on a "Fortschritte zurücksetzen" re-import -- see reset_student_progress_for_task
                teacher_score INTEGER,  -- migrate_048: teacher's override, NULL = not reviewed. Read via effective_checkpoint_score(), never `score` directly
                teacher_note TEXT,  -- short reason for the override, shown to nobody but the teacher
                student_feedback TEXT,  -- migrate_049: the ONE field on this table the student reads. teacher_note stays private -- rows were written under that promise
                reviewed_at TEXT,
                reviewed_by INTEGER,  -- admin.id, no FK (an admin row going away must not erase the review record)
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE,
                FOREIGN KEY (module_id) REFERENCES task(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoint_attempt_student_module
            ON checkpoint_attempt(student_id, module_id);

            CREATE INDEX IF NOT EXISTS idx_checkpoint_attempt_checkpoint
            ON checkpoint_attempt(checkpoint_id);

            -- Per-question answer log behind a checkpoint_attempt's aggregate score
            -- (migrate_047). Written as answers happen, before checkpoint_attempt
            -- exists -- see create_checkpoint_answer/create_checkpoint_attempt.
            -- checkpoint_id/checkpoint_attempt_id carry no FK constraint, same
            -- reasoning as checkpoint_attempt.checkpoint_id above.
            CREATE TABLE IF NOT EXISTS checkpoint_answer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkpoint_attempt_id INTEGER,
                student_id INTEGER NOT NULL,
                checkpoint_id INTEGER NOT NULL,
                session_uid TEXT NOT NULL,
                question_index INTEGER NOT NULL,
                attempt_no INTEGER NOT NULL,
                answer_text TEXT,
                correct INTEGER,  -- 0/1/NULL -- NULL = LLM grading failed, not "wrong"
                feedback TEXT,
                grader TEXT NOT NULL,  -- match/llm/fallback/error/mc/gaveup
                llm_model TEXT,
                hints_used_before INTEGER NOT NULL DEFAULT 0,
                gave_up INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                teacher_verdict INTEGER,  -- migrate_048: whether the KI's verdict was right (1=ja/0=nein), NOT what the answer was -- the admin UI asks "War die KI-Bewertung richtig?". Derive the answer's real correctness as `correct` when 1, `not correct` when 0. NULL = not judged. Calibration only -- never feeds the score
                teacher_note TEXT,
                prompt_version TEXT,  -- which system prompt graded this (llm_grading.prompt_version_for) -- without it, a prompt change makes old/new rows incomparable
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoint_answer_attempt
            ON checkpoint_answer(checkpoint_attempt_id);

            CREATE INDEX IF NOT EXISTS idx_checkpoint_answer_session
            ON checkpoint_answer(session_uid);

            CREATE INDEX IF NOT EXISTS idx_checkpoint_answer_student_checkpoint
            ON checkpoint_answer(student_id, checkpoint_id);

            CREATE INDEX IF NOT EXISTS idx_checkpoint_attempt_unreviewed
            ON checkpoint_attempt(timestamp) WHERE teacher_score IS NULL;

            -- Subtask visibility (per-class and per-student overrides)
            CREATE TABLE IF NOT EXISTS subtask_visibility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subtask_id INTEGER NOT NULL,
                klasse_id INTEGER,
                student_id INTEGER,
                enabled INTEGER DEFAULT 1,
                set_by_admin_id INTEGER,
                set_at TIMESTAMP DEFAULT (datetime('now','localtime')),
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

            -- Student's chosen branch for a given fork_group (one row per student per fork)
            CREATE TABLE IF NOT EXISTS student_fork_choice (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                fork_group TEXT NOT NULL,
                fork_branch TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(student_id, fork_group),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
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

            -- ============ Error Logging ============

            -- Error log for tracking application errors
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT (datetime('now','localtime')),
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
                timestamp DATETIME DEFAULT (datetime('now','localtime')),
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
                updated_at DATETIME DEFAULT (datetime('now','localtime'))
            );

            -- ============ Saved Reports ============

            -- Stored PDF reports for historical comparison
            CREATE TABLE IF NOT EXISTS saved_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,  -- 'class_simple', 'student_summary', 'student_complete'
                klasse_id INTEGER,
                student_id INTEGER,
                date_generated DATETIME DEFAULT (datetime('now','localtime')),
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
                timestamp DATETIME DEFAULT (datetime('now','localtime')),
                question_type TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_llm_usage_student_time
            ON llm_usage(student_id, timestamp);

            -- ============ Artifact Feedback ============

            -- Per-upload LLM checklist results for graded artifacts
            CREATE TABLE IF NOT EXISTS artifact_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subtask_id INTEGER NOT NULL,
                timestamp_local TEXT NOT NULL,
                timezone TEXT NOT NULL,
                feedback_json TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES student(id),
                FOREIGN KEY (subtask_id) REFERENCES subtask(id)
            );

            CREATE INDEX IF NOT EXISTS idx_artifact_feedback_student_subtask
            ON artifact_feedback(student_id, subtask_id);

            CREATE TABLE IF NOT EXISTS artifact_gate_attempt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                subtask_id INTEGER NOT NULL,
                timestamp_local TEXT NOT NULL,
                timezone TEXT NOT NULL,
                passed INTEGER NOT NULL,
                details_json TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES student(id),
                FOREIGN KEY (subtask_id) REFERENCES subtask(id)
            );

            CREATE INDEX IF NOT EXISTS idx_gate_attempt_student_subtask
            ON artifact_gate_attempt(student_id, subtask_id);

            -- Latest uploaded artifact file per (student, task/unit) -- overwritten on re-upload.
            -- Keyed by task, not subtask: units use the "gradual artifact building" pattern
            -- (docs/shared/mbi/content-design.md) -- one growing document per unit, uploaded
            -- fresh at each checkpoint, not a separate file per checkpoint.
            CREATE TABLE IF NOT EXISTS student_artifact_file (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                last_subtask_id INTEGER NOT NULL,
                original_filename TEXT NOT NULL,
                disk_filename TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                UNIQUE(student_id, task_id),
                FOREIGN KEY (student_id) REFERENCES student(id),
                FOREIGN KEY (task_id) REFERENCES task(id),
                FOREIGN KEY (last_subtask_id) REFERENCES subtask(id)
            );

            CREATE INDEX IF NOT EXISTS idx_student_artifact_file_student_task
            ON student_artifact_file(student_id, task_id);

            -- ============ Grading Service (grading-with-llm Phase 2) ============
            -- One row per imported batch from the grading service (spec §7/§10 Phase 2).
            -- Klasse/task-level summary; per-student outcomes live in grading_result.
            CREATE TABLE IF NOT EXISTS grading_run (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                klasse_id INTEGER,
                task_id INTEGER NOT NULL,
                rubric TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT,
                imported_at TEXT NOT NULL,
                graded_at TEXT,
                total_students INTEGER NOT NULL DEFAULT 0,
                flagged_count INTEGER NOT NULL DEFAULT 0,
                zero_score_count INTEGER NOT NULL DEFAULT 0,
                media_purged_at TEXT,
                UNIQUE(job_id),
                FOREIGN KEY (klasse_id) REFERENCES klasse(id),
                FOREIGN KEY (task_id) REFERENCES task(id)
            );

            CREATE INDEX IF NOT EXISTS idx_grading_run_klasse ON grading_run(klasse_id);
            CREATE INDEX IF NOT EXISTS idx_grading_run_task ON grading_run(task_id);

            -- Per-student outcome within a grading_run. State machine, per
            -- grading-service-deployment.md §7:
            --   imported -> under_review -> active -> (visible to student)
            --                    |-> corrected -> active  (teacher overrode a score)
            --                    |-> discarded            (bad run, re-grade)
            --                    |-> superseded            (another run made active instead)
            -- task_id is denormalized from grading_run so the partial unique index
            -- below can enforce "at most one active row per (student, artifact)"
            -- (spec §7) without a cross-table constraint, which SQLite can't express.
            CREATE TABLE IF NOT EXISTS grading_result (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grading_run_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                student_id INTEGER,
                netzwerk_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'imported',
                llm_total_score REAL,
                llm_max_score REAL,
                teacher_total_score REAL,
                note INTEGER,
                flagged INTEGER NOT NULL DEFAULT 0,
                confidence TEXT,
                error TEXT,
                criteria_json TEXT NOT NULL,
                document_file TEXT,
                media_json TEXT,
                media_skipped_json TEXT,
                reviewed_at TEXT,
                released_at TEXT,
                released_by INTEGER,
                superseded_by_id INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(grading_run_id, netzwerk_id),
                FOREIGN KEY (grading_run_id) REFERENCES grading_run(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES task(id),
                FOREIGN KEY (student_id) REFERENCES student(id),
                FOREIGN KEY (released_by) REFERENCES admin(id),
                FOREIGN KEY (superseded_by_id) REFERENCES grading_result(id)
            );

            CREATE INDEX IF NOT EXISTS idx_grading_result_run ON grading_result(grading_run_id);
            CREATE INDEX IF NOT EXISTS idx_grading_result_student ON grading_result(student_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_grading_result_one_active_per_artifact
            ON grading_result(student_id, task_id) WHERE status = 'active';

            -- ============ Warmup / Spaced Repetition ============

            -- Per-student per-question stats for spaced repetition.
            -- Keyed by question_hash (content hash, see _question_hash()) rather
            -- than position - an edited quiz that inserts/reorders a question
            -- must not silently attach history to the wrong one.
            CREATE TABLE IF NOT EXISTS warmup_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                task_id INTEGER,
                subtask_id INTEGER,
                question_hash TEXT NOT NULL,
                times_shown INTEGER NOT NULL DEFAULT 0,
                times_correct INTEGER NOT NULL DEFAULT 0,
                last_shown DATE,
                streak INTEGER NOT NULL DEFAULT 0,
                UNIQUE(student_id, task_id, subtask_id, question_hash),
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_warmup_student
            ON warmup_history(student_id, last_shown);

            -- Log of each warmup/practice session
            CREATE TABLE IF NOT EXISTS warmup_session (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                timestamp DATETIME DEFAULT (datetime('now','localtime')),
                questions_shown INTEGER NOT NULL DEFAULT 0,
                questions_correct INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                session_type TEXT NOT NULL DEFAULT 'warmup',  -- warmup/practice
                FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
            );
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


def update_klasse_name(klasse_id, name):
    """Rename a class in-place (same ID, so student progress/history stays attached)."""
    with db_session() as conn:
        conn.execute("UPDATE klasse SET name = ? WHERE id = ?", (name, klasse_id))


def update_klasse_klassenstufe(klasse_id, klassenstufe):
    """Set a class's grade level (5, 6, ...), or None to clear it."""
    with db_session() as conn:
        conn.execute("UPDATE klasse SET klassenstufe = ? WHERE id = ?", (klassenstufe, klasse_id))


def get_klasse_by_kurs_code(kurs_code):
    """Look up a class by its linked student_mapping.csv Kurs code (e.g.
    'GHU 5'). Returns None if no class is linked to that code yet -- see
    diff_klassen_kurs() for the CSV-vs-DB matching this backs."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM klasse WHERE kurs_code = ?", (kurs_code,)).fetchone()
        return dict(row) if row else None


def set_klasse_kurs_code(klasse_id, kurs_code):
    """Link a class to a student_mapping.csv Kurs code, or None to unlink."""
    with db_session() as conn:
        conn.execute("UPDATE klasse SET kurs_code = ? WHERE id = ?", (kurs_code, klasse_id))


def get_klasse(klasse_id):
    """Get a class by ID."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
        result = dict(row) if row else None
    return result


def get_klasse_by_name(name):
    """Get a class by exact name match (used by the student_mapping.csv
    Klassenstufe cross-check -- admin/bewertung/netzwerk-ids)."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM klasse WHERE name = ?", (name,)).fetchone()
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


def get_existing_netzwerk_ids():
    """Get all existing (non-null) student netzwerk_ids."""
    with db_session() as conn:
        rows = conn.execute("SELECT netzwerk_id FROM student WHERE netzwerk_id IS NOT NULL").fetchall()
        return {r['netzwerk_id'] for r in rows}


def get_all_students_with_netzwerk_id():
    """All students (any class, any school year) with their current
    netzwerk_id, lernpfad, a comma-joined list of class names and a
    comma-joined list of class ids, for the admin/bewertung/netzwerk-ids
    CSV matcher (the ids are what diff_student_enrollment() needs to tell
    whether a student's current class already matches the CSV's target)."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT s.id, s.nachname, s.vorname, s.netzwerk_id, s.lernpfad, "
            "GROUP_CONCAT(k.name, ', ') AS klassen, "
            "GROUP_CONCAT(k.id, ',') AS klasse_ids "
            "FROM student s "
            "LEFT JOIN student_klasse sk ON sk.student_id = s.id "
            "LEFT JOIN klasse k ON k.id = sk.klasse_id "
            "GROUP BY s.id ORDER BY s.nachname, s.vorname"
        ).fetchall()
        return [dict(r) for r in rows]


def update_student_netzwerk_id(student_id, netzwerk_id):
    """Overwrite one student's netzwerk_id (manual correction after CSV
    matching). Can raise sqlite3.IntegrityError -- the partial unique index
    idx_student_netzwerk_id rejects assigning an ID already used by another
    student; the caller should catch that per-row rather than let the whole
    batch fail."""
    with db_session() as conn:
        conn.execute("UPDATE student SET netzwerk_id = ? WHERE id = ?", (netzwerk_id, student_id))


def update_student_name(student_id, nachname, vorname):
    """Overwrite one student's nachname/vorname (manual correction after CSV
    matching -- e.g. the CSV carries a second given name Lernmanager doesn't
    have on record yet, like "Kirby" vs. "Kirby Philip")."""
    with db_session() as conn:
        conn.execute(
            "UPDATE student SET nachname = ?, vorname = ? WHERE id = ?",
            (nachname, vorname, student_id)
        )


def _vorname_prefix_match(a, b):
    """True if a and b are equal, or one is the other plus a further given
    name (e.g. "Kirby" / "Kirby Philip") -- the common way a school roster
    and Lernmanager's own records drift apart on a student with multiple
    given names, without being a different student."""
    a, b = a.strip().lower(), b.strip().lower()
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    return bool(shorter) and longer.startswith(shorter + ' ')


def diff_netzwerk_ids(csv_rows):
    """
    Cross-check CSV-provided real network logins against the DB roster.

    Reuses grading-with-llm/scripts/validate_student_ids.py's approach --
    exact matches, entries only on one side, and a first-4-chars similarity
    hint for likely renames/typos -- but resolves everything per student row
    (that script only ever printed a report; here each mismatch needs to map
    to one student so the admin can apply it with a click).

    csv_rows: list of {'nachname', 'vorname', 'login'} from
    utils.parse_netzwerk_csv().

    Also cross-checks Lernpfad: if the CSV has a Seilbahn column (see
    utils.parse_netzwerk_csv), a matched student whose 'seilbahn' cell is
    non-empty is expected to have lernpfad='seilbahn' in Lernmanager, and
    vice versa. Mismatches go in the returned 'lernpfad_mismatches' list.
    Rows/students only differ in login are unaffected -- this doesn't touch
    'updates'/'unchanged', it just adds a second, independent report.

    Returns {'updates', 'unchanged', 'csv_unmatched', 'db_unmatched',
    'lernpfad_mismatches', 'possible_matches'}:
      - updates: DB student found by name, CSV login differs from current netzwerk_id
      - unchanged: DB student found by name, CSV login already matches
      - csv_unmatched: CSV row whose name matched zero or >1 DB students
        (after possible_matches below have been pulled out)
      - db_unmatched: DB student with no matching CSV row (each gets
        'similar_csv_logins' -- CSV logins sharing the current ID's first 4
        chars, i.e. validate_student_ids.py's mismatch hint; also with
        possible_matches pulled out)
      - lernpfad_mismatches: matched students where CSV Seilbahn flag and
        DB lernpfad disagree, each {..student fields.., 'csv_seilbahn'}
      - possible_matches: leftover db_unmatched/csv_unmatched pairs the
        exact-name match above missed but are almost certainly the same
        student -- either an identical netzwerk_id (name spelling drifted,
        e.g. DB "Amelie Nele" vs. CSV "Amelie-Nele"), or same nachname with
        a vorname that's a further given name of the other (e.g. DB "Kirby"
        vs. CSV "Kirby Philip"). Common enough (school roster spelling
        conventions changing between exports) to warrant a one-click
        confirm instead of leaving them stuck as unexplained mismatches on
        both sides. Each dict is the student's fields plus
        'csv_nachname'/'csv_vorname'/'csv_login'.
    """
    students = get_all_students_with_netzwerk_id()

    def name_key(nachname, vorname):
        return (_normalize_umlauts(nachname.strip()).lower(), _normalize_umlauts(vorname.strip()).lower())

    by_name = {}
    for s in students:
        by_name.setdefault(name_key(s['nachname'], s['vorname']), []).append(s)

    matched_student_ids = set()
    updates, unchanged, csv_unmatched, lernpfad_mismatches = [], [], [], []

    for row in csv_rows:
        candidates = by_name.get(name_key(row['nachname'], row['vorname']), [])
        if len(candidates) != 1:
            csv_unmatched.append(row)
            continue
        student = candidates[0]
        matched_student_ids.add(student['id'])
        csv_login = row['login'].strip().lower()
        if (student['netzwerk_id'] or '') == csv_login:
            unchanged.append(student)
        else:
            updates.append({**student, 'csv_login': csv_login})

        csv_seilbahn = bool(row.get('seilbahn', '').strip())
        if csv_seilbahn != (student['lernpfad'] == 'seilbahn'):
            lernpfad_mismatches.append({**student, 'csv_seilbahn': csv_seilbahn})

    db_unmatched = [dict(s) for s in students if s['id'] not in matched_student_ids]

    csv_logins_unmatched = {r['login'].strip().lower() for r in csv_unmatched}
    for s in db_unmatched:
        prefix = (s['netzwerk_id'] or '')[:4]
        s['similar_csv_logins'] = sorted(l for l in csv_logins_unmatched if prefix and l[:4] == prefix)

    possible_matches = []
    matched_row_idx, matched_extra_student_ids = set(), set()

    def _add_possible_match(student, row_idx):
        row = csv_unmatched[row_idx]
        possible_matches.append({
            **student, 'csv_nachname': row['nachname'], 'csv_vorname': row['vorname'],
            'csv_login': row['login'].strip().lower(),
        })
        matched_row_idx.add(row_idx)
        matched_extra_student_ids.add(student['id'])

    # Pass 1: identical netzwerk_id -- the strongest possible signal, catches
    # cases where the login already matches but the name doesn't spell-match
    # (e.g. DB "Amelie Nele" vs. CSV "Amelie-Nele" -- punctuation drift, not
    # a different student), independent of nachname/vorname at all.
    csv_rows_by_login = {}
    for i, row in enumerate(csv_unmatched):
        csv_rows_by_login.setdefault(row['login'].strip().lower(), []).append(i)

    for s in db_unmatched:
        login = (s['netzwerk_id'] or '').strip().lower()
        candidates = [i for i in csv_rows_by_login.get(login, []) if i not in matched_row_idx]
        if login and len(candidates) == 1:
            _add_possible_match(s, candidates[0])

    # Pass 2: same nachname, vorname differs only by a further given name
    # (see _vorname_prefix_match) -- covers the remaining login-also-changed
    # cases pass 1 can't reach.
    for s in db_unmatched:
        if s['id'] in matched_extra_student_ids:
            continue
        s_nachname = _normalize_umlauts(s['nachname'].strip()).lower()
        for i, row in enumerate(csv_unmatched):
            if i in matched_row_idx:
                continue
            row_nachname = _normalize_umlauts(row['nachname'].strip()).lower()
            if s_nachname == row_nachname and _vorname_prefix_match(s['vorname'], row['vorname']):
                _add_possible_match(s, i)
                break

    db_unmatched = [s for s in db_unmatched if s['id'] not in matched_extra_student_ids]
    csv_unmatched = [r for i, r in enumerate(csv_unmatched) if i not in matched_row_idx]

    return {
        'updates': updates, 'unchanged': unchanged,
        'csv_unmatched': csv_unmatched, 'db_unmatched': db_unmatched,
        'lernpfad_mismatches': lernpfad_mismatches, 'possible_matches': possible_matches,
    }


def diff_klassenstufen(csv_rows):
    """
    Compare each CSV row's (Klasse, Klassenstufe) against Lernmanager's
    klasse.klassenstufe field. This is a class-level check, not a per-student
    one -- Klassenstufe is a fact about the class, so we dedupe to one entry
    per distinct Klasse name found in the CSV rather than repeating it once
    per student in that class.

    csv_rows: list of dicts from utils.parse_netzwerk_csv() -- rows lacking
    either the 'klasse' or 'klassenstufe' column value are skipped (the CSV
    upload may not always carry these columns).

    Returns list of dicts, one per distinct CSV Klasse name:
      {'klasse_name', 'csv_klassenstufe', 'db_klassenstufe', 'status'}
    """
    seen = {}
    for row in csv_rows:
        name = (row.get('klasse') or '').strip()
        stufe = (row.get('klassenstufe') or '').strip()
        if not name or not stufe:
            continue
        seen.setdefault(name, stufe)  # first CSV row for this class wins

    results = []
    for klasse_name, csv_stufe in sorted(seen.items()):
        klasse = get_klasse_by_name(klasse_name)
        entry = {
            'klasse_name': klasse_name,
            'csv_klassenstufe': csv_stufe,
        }

        if klasse is None:
            entry['db_klassenstufe'] = None
            entry['status'] = 'not_in_lernmanager'
        else:
            db_stufe = klasse['klassenstufe']
            entry['db_klassenstufe'] = db_stufe
            if db_stufe is None:
                entry['status'] = 'not_set'
            elif int(db_stufe) == int(csv_stufe):
                entry['status'] = 'match'
            else:
                entry['status'] = 'mismatch'

        results.append(entry)

    return results


def diff_klassen_kurs(csv_rows):
    """
    Group student_mapping.csv rows by (Klassenstufe, Kurs) -- Lernmanager's
    classes are combined groups of 2-3 CSV Klasse (course) values sharing
    one Kurs code (e.g. Kurs "GHU 5" = courses Ginkgo+Haie+Urvögel = class
    "Ginkgo-Haie-Urvögel 5"). Group size isn't fixed -- grade 7 only
    combines 2 courses per group this year, so this derives membership from
    the data instead of hardcoding a count.

    csv_rows: list of dicts from utils.parse_netzwerk_csv() -- rows missing
    'klassenstufe', 'kurs' or 'klasse' are skipped.

    For each group, resolves against the DB in three tiers:
      - 'linked': klasse.kurs_code already points to an existing class --
        no action needed, just confirms the ongoing link still holds.
      - 'suggested_link': no class has this kurs_code yet, but exactly one
        *unlinked* existing class looks like a match on course names (the
        one-time bootstrap case for classes that predate kurs_code) --
        admin confirms the link.
      - 'new': no match at all (e.g. this year's grade-7 groups) -- admin
        names and creates a new class.

    Returns list of dicts, one per distinct (Klassenstufe, Kurs) group:
      {'klassenstufe', 'kurs_code', 'klasse_names', 'status', 'klasse'
      (linked/suggested_link only), 'suggested_name' (new only)}
    """
    groups = {}
    for row in csv_rows:
        stufe = (row.get('klassenstufe') or '').strip()
        kurs = (row.get('kurs') or '').strip()
        klasse_name = (row.get('klasse') or '').strip()
        if not stufe or not kurs or not klasse_name:
            continue
        key = (stufe, kurs)
        group = groups.setdefault(key, {
            'klassenstufe': stufe, 'kurs_code': kurs, 'klasse_names': [],
        })
        if klasse_name not in group['klasse_names']:
            group['klasse_names'].append(klasse_name)

    unlinked_klassen = [k for k in get_all_klassen() if not k['kurs_code']]

    results = []
    for key in sorted(groups.keys()):
        group = groups[key]
        linked = get_klasse_by_kurs_code(group['kurs_code'])
        if linked:
            results.append({**group, 'status': 'linked', 'klasse': linked})
            continue

        suggested = _find_bootstrap_klasse_match(group['klasse_names'], group['klassenstufe'], unlinked_klassen)
        if suggested:
            results.append({**group, 'status': 'suggested_link', 'klasse': suggested})
        else:
            suggested_name = '-'.join(group['klasse_names']) + f" {group['klassenstufe']}"
            results.append({**group, 'status': 'new', 'suggested_name': suggested_name})

    return results


def _find_bootstrap_klasse_match(klasse_names, klassenstufe, unlinked_klassen):
    """One-time bootstrap matcher: does an unlinked class's name spell out
    exactly this CSV group's course names, for the same grade? Splits the
    class name on '-' and pulls the trailing grade-number token off the
    last part (e.g. "Ginkgo-Haie-Urvögel 5" -> courses
    {'ginkgo', 'haie', 'urvögel'}, grade '5'), then requires both the grade
    and the course-name set to match -- grade matters because two grades
    can share the same course-name set (e.g. GHU 5 and GHU 6), and set
    comparison is order-independent since CSV order and name order don't
    match (e.g. Seepferdchen-Krokodile-Schildkröten).

    Returns the single matching klasse dict, or None if zero or more than
    one class matches (ambiguous -- let the admin decide by hand instead
    of guessing).
    """
    wanted = {n.strip().lower() for n in klasse_names}
    wanted_stufe = str(klassenstufe).strip()

    matches = []
    for klasse in unlinked_klassen:
        tokens = klasse['name'].split('-')
        if not tokens:
            continue
        last_parts = tokens[-1].strip().rsplit(' ', 1)
        if len(last_parts) != 2 or not last_parts[1].isdigit():
            continue
        tokens[-1] = last_parts[0]
        name_stufe = last_parts[1]
        name_courses = {t.strip().lower() for t in tokens if t.strip()}
        if name_courses == wanted and name_stufe == wanted_stufe:
            matches.append(klasse)

    return matches[0] if len(matches) == 1 else None


def diff_student_enrollment(csv_rows, klassen_kurs_diff):
    """
    Cross-check each CSV row's target class (via its Kurs group, resolved
    by diff_klassen_kurs()) against the DB roster. This is the "create new
    students / move promoted students" half of the roster-sync check --
    diff_netzwerk_ids() already handles the netzwerk_id-only correction for
    students who don't need to change class.

    csv_rows: list of dicts from utils.parse_netzwerk_csv().
    klassen_kurs_diff: the return value of diff_klassen_kurs() for the same
    csv_rows -- supplies each group's resolved (or pending) target class.

    Matches an existing student primarily by netzwerk_id (CSV Login is
    stable year over year, per generate_netzwerk_id()), falling back to
    name matching (same normalization as diff_netzwerk_ids) only for rows
    with no netzwerk_id hit.

    Returns {'to_create', 'to_move', 'unchanged', 'ambiguous'}:
      - to_create: no DB student found -- needs create_student() +
        add_student_to_klasse(). Each row carries 'target_kurs_code' and
        either 'target_klasse' (existing/linked class dict) or
        'target_klasse_pending' (suggested name -- the group is still
        'new' in klassen_kurs_diff, so the class must be created first).
      - to_move: DB student found, current class differs from target.
        Carries 'from_klasse_id' (the single class to move them out of)
        plus the same target fields as to_create.
      - unchanged: DB student found, already in the target class.
      - ambiguous: DB student found but currently enrolled in zero or
        multiple classes, so there's no single unambiguous "from" class to
        move them out of -- left for the admin to sort out by hand rather
        than guessed.
    """
    groups_by_key = {(g['klassenstufe'], g['kurs_code']): g for g in klassen_kurs_diff}

    students = get_all_students_with_netzwerk_id()
    by_netzwerk_id = {s['netzwerk_id']: s for s in students if s['netzwerk_id']}

    def name_key(nachname, vorname):
        return (_normalize_umlauts(nachname.strip()).lower(), _normalize_umlauts(vorname.strip()).lower())

    by_name = {}
    for s in students:
        by_name.setdefault(name_key(s['nachname'], s['vorname']), []).append(s)

    to_create, to_move, unchanged, ambiguous = [], [], [], []

    for row in csv_rows:
        stufe = (row.get('klassenstufe') or '').strip()
        kurs = (row.get('kurs') or '').strip()
        if not stufe or not kurs:
            continue
        group = groups_by_key.get((stufe, kurs))
        if group is None:
            continue

        login = row['login'].strip().lower()
        target = {
            'nachname': row['nachname'], 'vorname': row['vorname'],
            'netzwerk_id': login, 'target_kurs_code': kurs,
        }
        if group['status'] == 'new':
            target['target_klasse_pending'] = group['suggested_name']
            target_klasse_id = None
        else:
            target['target_klasse'] = group['klasse']
            target_klasse_id = group['klasse']['id']

        student = by_netzwerk_id.get(login)
        if student is None:
            candidates = by_name.get(name_key(row['nachname'], row['vorname']), [])
            student = candidates[0] if len(candidates) == 1 else None

        if student is None:
            to_create.append(target)
            continue

        current_ids = [int(i) for i in (student['klasse_ids'] or '').split(',') if i]
        target['student'] = student

        if target_klasse_id is not None and target_klasse_id in current_ids:
            unchanged.append(target)
        elif len(current_ids) == 1:
            target['from_klasse_id'] = current_ids[0]
            to_move.append(target)
        else:
            ambiguous.append(target)

    return {
        'to_create': to_create, 'to_move': to_move,
        'unchanged': unchanged, 'ambiguous': ambiguous,
    }


def _normalize_umlauts(text):
    """ä/ö/ü/ß -> ae/oe/ue/ss. Same mapping as grading-with-llm's
    scripts/generate_student_ids.py (kept in sync by hand, not imported --
    that project isn't a dependency of this one)."""
    if not text:
        return ""
    replacements = {'ä': 'ae', 'Ä': 'ae', 'ö': 'oe', 'Ö': 'oe', 'ü': 'ue', 'Ü': 'ue', 'ß': 'ss'}
    for umlaut, replacement in replacements.items():
        text = text.replace(umlaut, replacement)
    return text


def generate_netzwerk_id(nachname, vorname, existing_ids):
    """
    Generate a school network ID: lastname.firstname, lowercase, umlauts
    normalized, 12 chars total max (7 lastname + 1 dot + 4 firstname, or less
    if lastname is shorter). Matches the format scan-folders produces for
    submission folder names, so grading-service imports can match a folder to
    an enrolled student without fuzzy nachname/vorname matching. Algorithm
    ported from grading-with-llm/scripts/generate_student_ids.py.

    existing_ids: set of already-assigned netzwerk_ids (this call's own
    generated ones must be added by the caller between calls, same as
    generate_username's existing_usernames convention) -- collisions get a
    numeric suffix (musterm.mari, musterm.mari2, ...).
    """
    last = ''.join(c for c in _normalize_umlauts(nachname.strip()).lower() if c.isalnum())
    first = ''.join(c for c in _normalize_umlauts(vorname.strip()).lower() if c.isalnum())
    id_last = last[:7]
    id_first = first[:12 - len(id_last) - 1]
    base_id = f"{id_last}.{id_first}"

    if base_id not in existing_ids:
        return base_id
    n = 2
    while f"{base_id}{n}" in existing_ids:
        n += 1
    return f"{base_id}{n}"


def create_student(nachname, vorname, username, password, lernpfad='bergweg', netzwerk_id=None):
    """Create a new student."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO student (nachname, vorname, username, password_hash, lernpfad, netzwerk_id) VALUES (?, ?, ?, ?, ?, ?)",
            (nachname, vorname, username, hash_password(password), lernpfad, netzwerk_id)
        )
        return cursor.lastrowid


def set_class_lernpfad(klasse_id, lernpfad):
    """Set lernpfad for all students in a class."""
    with db_session() as conn:
        conn.execute(
            "UPDATE student SET lernpfad = ? WHERE id IN (SELECT student_id FROM student_klasse WHERE klasse_id = ?)",
            (lernpfad, klasse_id)
        )


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
    """Delete a student and all associated data. Returns disk filenames of removed artifact uploads (caller must unlink)."""
    with db_session() as conn:
        disk_filenames = [r[0] for r in conn.execute(
            "SELECT disk_filename FROM student_artifact_file WHERE student_id = ?", (student_id,)
        ).fetchall()]
        # Tables without ON DELETE CASCADE must be cleaned up explicitly
        conn.execute(
            "DELETE FROM analytics_events WHERE user_id = ? AND user_type = 'student'",
            (student_id,)
        )
        conn.execute("DELETE FROM unterricht_student WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM artifact_feedback WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM student_artifact_file WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM student WHERE id = ?", (student_id,))
    return disk_filenames


def delete_all_students_in_klasse(klasse_id):
    """Delete all students in a class (DSGVO year-end cleanup). Returns disk filenames of removed artifact uploads."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT student_id FROM student_klasse WHERE klasse_id = ?", (klasse_id,)
        ).fetchall()
    disk_filenames = []
    for row in rows:
        disk_filenames.extend(delete_student(row['student_id']))
    return disk_filenames


def get_student_data_summary(student_id):
    """Return record counts for a student (Art. 15 DSGVO Auskunft)."""
    with db_session() as conn:
        task_ids = [r['id'] for r in conn.execute(
            "SELECT id FROM student_task WHERE student_id = ?", (student_id,)
        ).fetchall()]
        placeholders = ','.join('?' * len(task_ids)) if task_ids else '0'
        quiz_count = conn.execute(
            f"SELECT COUNT(*) FROM quiz_attempt WHERE student_task_id IN ({placeholders})",
            task_ids
        ).fetchone()[0] if task_ids else 0
        return {
            'quiz_attempts': quiz_count,
            'warmup_sessions': conn.execute(
                "SELECT COUNT(*) FROM warmup_session WHERE student_id = ?", (student_id,)
            ).fetchone()[0],
            'analytics_events': conn.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE user_id = ? AND user_type = 'student'",
                (student_id,)
            ).fetchone()[0],
            'llm_quiz_gradings': conn.execute(
                "SELECT COUNT(*) FROM llm_usage WHERE student_id = ? AND question_type != 'artifact_feedback'",
                (student_id,)
            ).fetchone()[0],
            'ki_aufgabenchecks': conn.execute(
                "SELECT COUNT(*) FROM artifact_feedback WHERE student_id = ?", (student_id,)
            ).fetchone()[0],
        }


def get_student_data_export(student_id):
    """Return all stored data for a student as a dict (Art. 15 / Art. 17 DSGVO)."""
    with db_session() as conn:
        student = dict(conn.execute(
            "SELECT id, vorname, nachname, username, lernpfad FROM student WHERE id = ?",
            (student_id,)
        ).fetchone())

        task_rows = conn.execute(
            "SELECT id, task_id FROM student_task WHERE student_id = ?", (student_id,)
        ).fetchall()
        task_ids = [r['id'] for r in task_rows]
        placeholders = ','.join('?' * len(task_ids)) if task_ids else '0'

        quiz_attempts = [dict(r) for r in conn.execute(
            f"SELECT qa.timestamp, qa.punkte, qa.max_punkte, qa.bestanden "
            f"FROM quiz_attempt qa WHERE qa.student_task_id IN ({placeholders})",
            task_ids
        ).fetchall()] if task_ids else []

        warmup_sessions = [dict(r) for r in conn.execute(
            "SELECT timestamp, session_type, questions_shown, questions_correct "
            "FROM warmup_session WHERE student_id = ?", (student_id,)
        ).fetchall()]

        analytics_events = [dict(r) for r in conn.execute(
            "SELECT timestamp, event_type, metadata FROM analytics_events "
            "WHERE user_id = ? AND user_type = 'student' ORDER BY timestamp DESC",
            (student_id,)
        ).fetchall()]

        llm_usage = [dict(r) for r in conn.execute(
            "SELECT timestamp, question_type, tokens_used FROM llm_usage "
            "WHERE student_id = ? ORDER BY timestamp DESC", (student_id,)
        ).fetchall()]

        artifact_feedback = [dict(r) for r in conn.execute(
            "SELECT timestamp_local, subtask_id, feedback_json FROM artifact_feedback "
            "WHERE student_id = ? ORDER BY timestamp_local DESC", (student_id,)
        ).fetchall()]

    return {
        'student': student,
        'quiz_attempts': quiz_attempts,
        'warmup_sessions': warmup_sessions,
        'analytics_events': analytics_events,
        'llm_usage': llm_usage,
        'artifact_feedback': artifact_feedback,
    }


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
            LEFT JOIN student_task st ON st.id = (
                SELECT id FROM student_task
                WHERE student_id = s.id AND klasse_id = ? AND abgeschlossen = 0 AND rolle = 'primary'
                ORDER BY id DESC LIMIT 1
            )
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


def get_effective_transparency_mode(student_id, klasse_id=None):
    """Return True if LLM transparency mode is active for this student/class context.

    Class override (NULL=no opinion, 0=force off, 1=force on) takes precedence.
    Falls back to student's own llm_transparency_mode setting.
    """
    with db_session() as conn:
        if klasse_id:
            row = conn.execute(
                "SELECT llm_transparency_mode FROM klasse WHERE id = ?", (klasse_id,)
            ).fetchone()
            if row and row['llm_transparency_mode'] is not None:
                return bool(row['llm_transparency_mode'])
        row = conn.execute(
            "SELECT llm_transparency_mode FROM student WHERE id = ?", (student_id,)
        ).fetchone()
        return bool(row['llm_transparency_mode']) if row else False


def set_klasse_transparency_mode(klasse_id, mode):
    """Set class-level transparency override. mode: None, 0, or 1."""
    with db_session() as conn:
        conn.execute(
            "UPDATE klasse SET llm_transparency_mode = ? WHERE id = ?", (mode, klasse_id)
        )


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


def get_task_by_unit_slug(unit_slug):
    """Get a task by its unit_slug (Clayden-style connections). Returns None if not found."""
    if not unit_slug:
        return None
    with db_session() as conn:
        row = conn.execute("SELECT * FROM task WHERE unit_slug = ?", (unit_slug,)).fetchone()
        return dict(row) if row else None


def create_task(name, beschreibung, lernziel, fach, stufe, kategorie, quiz_json=None, number=0, why_learn_this=None, lernziel_schueler=None, module_tier='kern_standard', unit_slug=None, connections_json=None):
    """Create a new task."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO task (name, number, beschreibung, lernziel, lernziel_schueler, fach, stufe, kategorie, quiz_json, why_learn_this, module_tier, unit_slug, connections_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, number, beschreibung, lernziel, lernziel_schueler, fach, stufe, kategorie, quiz_json, why_learn_this, module_tier, unit_slug, connections_json)
        )
        return cursor.lastrowid


def update_task(task_id, name, beschreibung, lernziel, fach, stufe, kategorie, quiz_json=None, number=0, why_learn_this=None, subtask_quiz_required=None, lernziel_schueler=None, module_tier='kern_standard', unit_slug=None, connections_json=None):
    """Update a task."""
    with db_session() as conn:
        conn.execute('''
            UPDATE task SET name=?, number=?, beschreibung=?, lernziel=?, lernziel_schueler=?, fach=?, stufe=?,
            kategorie=?, quiz_json=?, why_learn_this=?, module_tier=?, unit_slug=?, connections_json=? WHERE id=?
        ''', (name, number, beschreibung, lernziel, lernziel_schueler, fach, stufe, kategorie, quiz_json, why_learn_this, module_tier, unit_slug, connections_json, task_id))
        if subtask_quiz_required is not None:
            conn.execute(
                "UPDATE task SET subtask_quiz_required = ? WHERE id = ?",
                (subtask_quiz_required, task_id)
            )


def get_looking_forward_to(unit_slug):
    """Inverse of connections.building_on, computed at render time (not stored).

    Unit A "looks forward to" every unit B where A appears in B's building_on
    (docs/shared/chemie/technical.md § Clayden-style prerequisites). Computing
    this fresh avoids two files (or one author, twice) drifting out of sync as
    building_on entries change.
    """
    if not unit_slug:
        return []
    with db_session() as conn:
        rows = conn.execute(
            "SELECT name, unit_slug, connections_json FROM task WHERE connections_json IS NOT NULL"
        ).fetchall()

    result = []
    for row in rows:
        try:
            connections = json.loads(row['connections_json'])
        except (json.JSONDecodeError, TypeError):
            continue
        for entry in connections.get('building_on', []):
            if entry.get('unit') == unit_slug:
                result.append({
                    'unit': row['unit_slug'],
                    'label': row['name'],
                    'strength': entry.get('strength', 'hard'),
                })
    return result


def get_task_deletion_impact(task_id):
    """Student data that delete_task() would destroy along with the topic.

    Surfaced in the delete confirmation so a teacher is never surprised by
    losing released grades -- those are the only irreplaceable rows here.
    """
    with db_session() as conn:
        def count(sql):
            return conn.execute(sql, (task_id,)).fetchone()[0]

        return {
            'students': count("SELECT COUNT(*) FROM student_task WHERE task_id = ?"),
            'artifact_files': count("SELECT COUNT(*) FROM student_artifact_file WHERE task_id = ?"),
            'grading_runs': count("SELECT COUNT(*) FROM grading_run WHERE task_id = ?"),
            'grading_results': count("SELECT COUNT(*) FROM grading_result WHERE task_id = ?"),
            'released_grades': count(
                "SELECT COUNT(*) FROM grading_result WHERE task_id = ? AND released_at IS NOT NULL"
            ),
        }


def delete_task(task_id):
    """Delete a task and its dependent rows.

    subtask/material/student_task cascade via FK ON DELETE CASCADE, but
    artifact_feedback, artifact_gate_attempt, student_artifact_file,
    grading_run and grading_result were added without cascade (SQLite can't
    ALTER a FK in place), so they're cleared explicitly here to avoid an
    IntegrityError. Those six are the complete set of non-cascading FKs into
    task/subtask -- keep this in sync when adding another one.

    Returns (student_artifact_disk_filenames, material_pfade_to_unlink) for
    the caller to remove from disk. Material filenames aren't task-scoped
    (ZIP-imported pfad values are plain content filenames, no task_id
    prefix -- see docs/shared/lernmanager/conventions.md), so a pfad is only
    safe to unlink once no other task's material row still references it.
    """
    with db_session() as conn:
        subtask_ids = [r['id'] for r in conn.execute(
            "SELECT id FROM subtask WHERE task_id = ?", (task_id,)
        ).fetchall()]
        if subtask_ids:
            ph = ','.join('?' * len(subtask_ids))
            conn.execute(f"DELETE FROM artifact_feedback WHERE subtask_id IN ({ph})", subtask_ids)
            conn.execute(f"DELETE FROM artifact_gate_attempt WHERE subtask_id IN ({ph})", subtask_ids)

        student_artifact_disk_filenames = [r['disk_filename'] for r in conn.execute(
            "SELECT disk_filename FROM student_artifact_file WHERE task_id = ?", (task_id,)
        ).fetchall()]
        conn.execute("DELETE FROM student_artifact_file WHERE task_id = ?", (task_id,))

        # Grading runs reference the topic's rubric, so they are meaningless
        # (and unreachable in /admin/grading/runs) once the topic is gone.
        # grading_result first -- it also FKs grading_run.
        conn.execute("DELETE FROM grading_result WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM grading_run WHERE task_id = ?", (task_id,))

        material_pfade = [r['pfad'] for r in conn.execute(
            "SELECT pfad FROM material WHERE task_id = ? AND typ = 'datei'", (task_id,)
        ).fetchall()]

        conn.execute("DELETE FROM task WHERE id = ?", (task_id,))  # cascades subtask/material/student_task

        material_pfade_to_unlink = [
            pfad for pfad in material_pfade
            if conn.execute(
                "SELECT 1 FROM material WHERE pfad = ? AND typ = 'datei'", (pfad,)
            ).fetchone() is None
        ]

    return student_artifact_disk_filenames, material_pfade_to_unlink


def reset_student_progress_for_task(task_id):
    """Reset all student progress for a task while preserving assignments.

    Deletes student_subtask, quiz_attempt, warmup_history and checkpoint_attempt
    records and resets student_task completion flags. student_task rows stay
    intact so students remain assigned to the topic.
    """
    with db_session() as conn:
        # Get all student_task IDs and subtask IDs for this task
        st_rows = conn.execute(
            "SELECT id FROM student_task WHERE task_id = ?", (task_id,)
        ).fetchall()
        st_ids = [r['id'] for r in st_rows]

        sub_rows = conn.execute(
            "SELECT id FROM subtask WHERE task_id = ?", (task_id,)
        ).fetchall()
        sub_ids = [r['id'] for r in sub_rows]

        if st_ids:
            ph = ','.join('?' * len(st_ids))
            conn.execute(f"DELETE FROM student_subtask WHERE student_task_id IN ({ph})", st_ids)
            conn.execute(f"DELETE FROM quiz_attempt WHERE student_task_id IN ({ph})", st_ids)

            # Deduplicate: a student may have multiple student_task rows for the
            # same task+klasse (history-preserving pattern). Setting all to
            # abgeschlossen=0 would violate idx_one_active_primary. Keep only
            # the newest row per (student_id, klasse_id) and delete the rest.
            conn.execute("""
                DELETE FROM student_task
                WHERE task_id = ? AND id NOT IN (
                    SELECT MAX(id) FROM student_task
                    WHERE task_id = ?
                    GROUP BY student_id, klasse_id
                )
            """, (task_id, task_id))

            # Refresh st_ids after dedup
            st_rows = conn.execute(
                "SELECT id FROM student_task WHERE task_id = ?", (task_id,)
            ).fetchall()
            st_ids = [r['id'] for r in st_rows]

            if st_ids:
                ph = ','.join('?' * len(st_ids))
                # Only unset abgeschlossen for students who don't already have
                # a different active primary topic in the same class — otherwise
                # we'd create two abgeschlossen=0 rows and violate idx_one_active_primary.
                conn.execute(f"""
                    UPDATE student_task SET abgeschlossen = 0, manuell_abgeschlossen = 0
                    WHERE id IN ({ph})
                    AND NOT EXISTS (
                        SELECT 1 FROM student_task st2
                        WHERE st2.student_id = student_task.student_id
                        AND st2.klasse_id = student_task.klasse_id
                        AND st2.abgeschlossen = 0
                        AND st2.rolle = 'primary'
                        AND st2.id != student_task.id
                    )
                """, st_ids)

        if sub_ids:
            ph = ','.join('?' * len(sub_ids))
            conn.execute(f"DELETE FROM warmup_history WHERE subtask_id IN ({ph})", sub_ids)

        # Also clear warmup_history linked by task_id
        conn.execute("DELETE FROM warmup_history WHERE task_id = ?", (task_id,))

        # Chemie Quiz-checkpoints log to checkpoint_attempt instead of quiz_attempt
        # (see has_passed_subtask_quiz) — student_id/module_id scoped, not student_task_id.
        # Soft-delete (supersede), not DELETE: the score is a real grade component
        # (Kern-Sperre/Punktekonto), not just progress-tracking, so a content
        # re-import must not erase it. has_passed_subtask_quiz ignores superseded
        # rows, so the progression gate still resets correctly (the original reason
        # this was a DELETE, commit f9d6a24) while the grade record survives.
        conn.execute(
            "UPDATE checkpoint_attempt SET superseded_at = ? "
            "WHERE module_id = ? AND superseded_at IS NULL",
            (now_local(), task_id)
        )


# ============ Topic Queue ============

def get_topic_queue(klasse_id):
    """Get ordered topic queue for a class.

    Returns list of dicts with position, task_id, name, fach, stufe, kategorie.
    Empty list if no queue defined.
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT tq.position, tq.task_id, t.name, t.fach, t.stufe, t.kategorie
            FROM topic_queue tq
            JOIN task t ON tq.task_id = t.id
            WHERE tq.klasse_id = ?
            ORDER BY tq.position
        ''', (klasse_id,)).fetchall()
        return [dict(r) for r in rows]


def set_topic_queue(klasse_id, task_ids_ordered):
    """Replace the topic queue for a class with the given ordered task IDs."""
    with db_session() as conn:
        conn.execute("DELETE FROM topic_queue WHERE klasse_id = ?", (klasse_id,))
        for pos, task_id in enumerate(task_ids_ordered, start=1):
            conn.execute(
                "INSERT INTO topic_queue (klasse_id, task_id, position) VALUES (?, ?, ?)",
                (klasse_id, task_id, pos)
            )


def get_next_queued_topic(klasse_id, current_task_id):
    """Get the next topic in queue after current_task_id.

    Returns dict with task_id, name, fach, stufe or None.
    """
    with db_session() as conn:
        current = conn.execute(
            "SELECT position FROM topic_queue WHERE klasse_id = ? AND task_id = ?",
            (klasse_id, current_task_id)
        ).fetchone()
        if not current:
            return None
        row = conn.execute('''
            SELECT tq.task_id, t.name, t.fach, t.stufe
            FROM topic_queue tq
            JOIN task t ON tq.task_id = t.id
            WHERE tq.klasse_id = ? AND tq.position = ?
        ''', (klasse_id, current['position'] + 1)).fetchone()
        return dict(row) if row else None


def get_queue_position(klasse_id, task_id):
    """Get position and total count for a task in a class queue.

    Returns (position, total) or (None, None) if not in queue.
    """
    with db_session() as conn:
        row = conn.execute(
            "SELECT position FROM topic_queue WHERE klasse_id = ? AND task_id = ?",
            (klasse_id, task_id)
        ).fetchone()
        if not row:
            return None, None
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM topic_queue WHERE klasse_id = ?",
            (klasse_id,)
        ).fetchone()['cnt']
        return row['position'], total


# ============ Task Export ============

def export_task_to_dict(task_id):
    """Export a single task with all related data as a dictionary.

    Returns a dict matching the import format from import_task.py, so that
    exported JSON can be edited and re-imported.

    Return format (see import_task.py):
        {
            'name': ..., 'number': ..., 'beschreibung': ..., 'lernziel': ...,
            'fach': ..., 'stufe': ..., 'kategorie': ..., 'why_learn_this': ...,
            'subtasks': [{'beschreibung': ..., 'reihenfolge': ..., 'estimated_minutes': ...}],
            'materials': [{'typ': ..., 'pfad': ..., 'beschreibung': ...}],
            'quiz': {'questions': [...]} or None,
        }
    """
    task = get_task(task_id)
    if (task is None):
        return None
    else:

        subtasks = get_subtasks(task_id)
        materials = get_materials(task_id)
        material_assignments = get_material_subtask_assignments(task_id)

        # Build subtask ID -> reihenfolge lookup
        subtask_id_to_pos = {s['id']: s['reihenfolge'] for s in subtasks}

        subtasks_data = []
        for subtask in subtasks:
            st_data = {
                'beschreibung': subtask['beschreibung'],
                'reihenfolge': subtask['reihenfolge'],
                'estimated_minutes': subtask['estimated_minutes'],
                'path': subtask.get('path'),
                'path_model': subtask.get('path_model', 'skip'),
                'fertig_wenn': subtask.get('fertig_wenn') or None,
                'tipps': subtask.get('tipps') or None,
                'checkpoint_type': subtask.get('checkpoint_type') or None,
                'kern_standard_tag': subtask.get('kern_standard_tag') or None,
                'checkpoint_hints': json.loads(subtask['checkpoint_hints_json']) if subtask.get('checkpoint_hints_json') else None,
                'fork_group': subtask.get('fork_group') or None,
                'fork_branch': subtask.get('fork_branch') or None,
                'fork_branch_label': subtask.get('fork_branch_label') or None,
                'fork_branch_note': subtask.get('fork_branch_note') or None,
                'fork_required': bool(subtask.get('fork_required', 1)) if subtask.get('fork_group') else None,
            }
            if subtask.get('quiz_json'):
                st_data['quiz'] = json.loads(subtask['quiz_json'])
            if subtask.get('graded_artifact_json'):
                st_data['graded_artifact'] = json.loads(subtask['graded_artifact_json'])
            if subtask.get('artifact_gate_json'):
                st_data['artifact_gate'] = json.loads(subtask['artifact_gate_json'])
            subtasks_data.append(st_data)

        materials_data = []
        for material in materials:
            mat_data = {
                'typ': material['typ'],
                'pfad': material['pfad'],
                'beschreibung': material['beschreibung'],
                'attribution': material.get('attribution')
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
            'module_tier': task.get('module_tier', 'kern_standard'),
            'subtasks': subtasks_data,
            'materials': materials_data,
            'quiz': quiz_data,
        }
        return data
          
        


def export_all_tasks():
    """Export all tasks. Wraps each task with export_task_to_dict()."""
    tasks = get_all_tasks()
    return [export_task_to_dict(t['id']) for t in tasks]


# ============ Learning Paths ============

PATH_ORDER = {'wanderweg': 0, 'bergweg': 1, 'gipfeltour': 2}
VALID_PATHS = set(PATH_ORDER) | {'seilbahn'}


def is_subtask_required_for_path(subtask, student_path):
    """Check if a subtask is required for the student's learning path.

    Seilbahn is non-cumulative: seilbahn students only do seilbahn tasks;
    main-path students never see seilbahn tasks as required.

    For main paths (wanderweg/bergweg/gipfeltour):
      path_model='depth' → always required (all paths do it, different grading)
      path_model='skip'  → required if subtask's path level <= student's path level
    """
    if not student_path or student_path not in VALID_PATHS:
        return True  # No path set → treat all as required (legacy)
    subtask_path = subtask.get('path')
    if student_path == 'seilbahn':
        return subtask_path == 'seilbahn'
    # Main paths: seilbahn tasks are never required
    if subtask_path == 'seilbahn':
        return False
    if not subtask_path or subtask_path not in PATH_ORDER:
        return True  # No path on subtask → required for all main paths
    if subtask.get('path_model') == 'depth':
        return True
    # 'skip' model: required if subtask path <= student path
    return PATH_ORDER[subtask_path] <= PATH_ORDER[student_path]


def is_question_visible_for_path(question, student_path):
    """Whether a quiz question should be shown to a student on student_path.

    Cumulative like is_subtask_required_for_path, but no path_model dimension
    (a question is either shown or not). No 'path' key -> visible to everyone,
    so existing quizzes without per-question path tags are unaffected.
    """
    question_path = question.get('path')
    if not question_path or question_path not in VALID_PATHS:
        return True
    if not student_path or student_path not in VALID_PATHS:
        return True
    if student_path == 'seilbahn':
        return question_path == 'seilbahn'
    if question_path == 'seilbahn':
        return False
    return PATH_ORDER[question_path] <= PATH_ORDER[student_path]


# ============ Fork/Choice ============
# Design: docs/shared/lernmanager/fork-choice-artifact-model.md

def get_pending_fork_groups(task_id, student_id):
    """Fork groups on this task with no stored choice yet for this student.

    Returns an ordered list (by min reihenfolge) of dicts:
    {fork_group, min_reihenfolge, branches: [{branch, label, note}, ...]},
    branches ordered by their first subtask's reihenfolge. Used both to block
    premature topic completion (any pending group blocks it) and to render
    the branch-selection card + placeholder progress dot.
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT fork_group, fork_branch, fork_branch_label, fork_branch_note, reihenfolge
            FROM subtask
            WHERE task_id = ? AND fork_group IS NOT NULL AND COALESCE(hidden, 0) = 0
            ORDER BY reihenfolge
        ''', (task_id,)).fetchall()
        if not rows:
            return []
        chosen = {
            row['fork_group'] for row in conn.execute(
                "SELECT fork_group FROM student_fork_choice WHERE student_id = ?", (student_id,)
            ).fetchall()
        }

    groups = {}
    for r in rows:
        group = r['fork_group']
        if group in chosen:
            continue
        entry = groups.setdefault(group, {'fork_group': group, 'min_reihenfolge': r['reihenfolge'], 'branches': {}})
        entry['min_reihenfolge'] = min(entry['min_reihenfolge'], r['reihenfolge'])
        branch = entry['branches'].setdefault(r['fork_branch'], {
            'branch': r['fork_branch'], 'label': None, 'note': None, 'first_reihenfolge': r['reihenfolge']
        })
        branch['first_reihenfolge'] = min(branch['first_reihenfolge'], r['reihenfolge'])
        if r['fork_branch_label']:
            branch['label'] = r['fork_branch_label']
        if r['fork_branch_note']:
            branch['note'] = r['fork_branch_note']

    result = []
    for group in sorted(groups.values(), key=lambda g: g['min_reihenfolge']):
        branches = sorted(group['branches'].values(), key=lambda b: b['first_reihenfolge'])
        for b in branches:
            b.pop('first_reihenfolge')
        result.append({
            'fork_group': group['fork_group'],
            'min_reihenfolge': group['min_reihenfolge'],
            'branches': branches,
        })
    return result


def get_fork_branches(task_id, fork_group):
    """Set of valid branch keys for a fork_group, regardless of choice state.

    Used to validate a branch pick even when re-picking an already-chosen
    group (get_pending_fork_groups only covers unresolved ones).
    """
    with db_session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT fork_branch FROM subtask WHERE task_id = ? AND fork_group = ?",
            (task_id, fork_group)
        ).fetchall()
        return {r['fork_branch'] for r in rows}


def get_student_fork_choice(student_id, fork_group):
    """The branch a student already picked for fork_group, or None."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT fork_branch FROM student_fork_choice WHERE student_id = ? AND fork_group = ?",
            (student_id, fork_group)
        ).fetchone()
        return row['fork_branch'] if row else None


def is_fork_choice_locked(student_id, fork_group, fork_branch):
    """True once the student has completed a subtask in the chosen branch.

    Matches the design doc's decision 2: the pick can be revised freely up to
    that point, then it's locked (a re-pick would orphan completed work).
    """
    with db_session() as conn:
        row = conn.execute('''
            SELECT 1 FROM subtask s
            JOIN student_subtask ss ON ss.subtask_id = s.id
            JOIN student_task st ON st.id = ss.student_task_id
            WHERE st.student_id = ? AND s.fork_group = ? AND s.fork_branch = ? AND ss.erledigt = 1
            LIMIT 1
        ''', (student_id, fork_group, fork_branch)).fetchone()
        return row is not None


def set_student_fork_choice(student_id, fork_group, fork_branch):
    """Store/update a student's branch pick. Caller must check is_fork_choice_locked first."""
    with db_session() as conn:
        conn.execute('''
            INSERT INTO student_fork_choice (student_id, fork_group, fork_branch, timestamp)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(student_id, fork_group) DO UPDATE SET
                fork_branch = excluded.fork_branch, timestamp = excluded.timestamp
        ''', (student_id, fork_group, fork_branch))


def get_student_fork_choices(student_id):
    """All of a student's fork choices, across all their tasks, with reassignment metadata.

    Returns a list of dicts: {fork_group, fork_branch, task_id, task_name,
    branches: [{branch, label}, ...]} — one row per (task, fork_group) the
    student has picked a branch for. Used by the admin student-detail page
    to let a teacher reassign a pick (bypasses the student-side lock — see
    docs/shared/lernmanager/fork-choice-artifact-model.md decision 1).
    """
    with db_session() as conn:
        choices = conn.execute(
            "SELECT fork_group, fork_branch FROM student_fork_choice WHERE student_id = ?",
            (student_id,)
        ).fetchall()
        result = []
        for c in choices:
            branch_rows = conn.execute('''
                SELECT DISTINCT s.fork_branch, s.fork_branch_label, s.task_id, t.name as task_name
                FROM subtask s JOIN task t ON t.id = s.task_id
                WHERE s.fork_group = ?
            ''', (c['fork_group'],)).fetchall()
            if not branch_rows:
                continue
            task_id = branch_rows[0]['task_id']
            task_name = branch_rows[0]['task_name']
            labels = {}
            for r in branch_rows:
                if r['fork_branch_label']:
                    labels[r['fork_branch']] = r['fork_branch_label']
            branches = sorted({r['fork_branch'] for r in branch_rows})
            result.append({
                'fork_group': c['fork_group'],
                'fork_branch': c['fork_branch'],
                'task_id': task_id,
                'task_name': task_name,
                'branches': [{'branch': b, 'label': labels.get(b, b)} for b in branches],
            })
        return result


def _filter_fork_subtasks(subtasks, student_id):
    """Resolve fork_group subtasks against student_fork_choice.

    Unresolved fork_group: all its subtasks (every branch) are excluded from
    the list entirely — position-indexing (_resolve_subtask_by_position and
    everything built on it) stays undisturbed; the template renders a single
    placeholder dot instead (see get_pending_fork_groups). Resolved: only the
    chosen branch's subtasks remain at their normal position; sibling
    branches are dropped (fork_required truthy) or kept non-required
    (fork_required=0, Zusatz — reuses the existing '.optional' dot styling).
    """
    fork_groups = {s['fork_group'] for s in subtasks if s.get('fork_group')}
    if not fork_groups:
        return subtasks

    with db_session() as conn:
        placeholders = ','.join('?' * len(fork_groups))
        choices = {
            row['fork_group']: row['fork_branch']
            for row in conn.execute(
                f"SELECT fork_group, fork_branch FROM student_fork_choice "
                f"WHERE student_id = ? AND fork_group IN ({placeholders})",
                [student_id, *fork_groups]
            ).fetchall()
        }

    result = []
    for s in subtasks:
        group = s.get('fork_group')
        if not group:
            result.append(s)
            continue
        chosen = choices.get(group)
        if chosen is None:
            continue
        if s.get('fork_branch') == chosen:
            result.append(s)
        elif not s.get('fork_required', 1):
            s['required'] = False
            result.append(s)
    return result


# ============ Subtask functions ============

def get_subtasks(task_id):
    """Get subtasks for a task."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM subtask WHERE task_id = ? ORDER BY reihenfolge",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def create_subtask(task_id, beschreibung, reihenfolge=0, estimated_minutes=None, quiz_json=None,
                   path=None, path_model='skip', graded_artifact_json=None, fertig_wenn=None, tipps=None,
                   artifact_gate_json=None, checkpoint_type=None, kern_standard_tag=None,
                   checkpoint_hints_json=None, fork_group=None, fork_branch=None,
                   fork_branch_label=None, fork_branch_note=None, fork_required=1, is_intro=0):
    """Create a subtask."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO subtask (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json, path, path_model, graded_artifact_json, artifact_gate_json, fertig_wenn, tipps, checkpoint_type, kern_standard_tag, checkpoint_hints_json, fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required, is_intro) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json, path, path_model, graded_artifact_json, artifact_gate_json, fertig_wenn, tipps, checkpoint_type, kern_standard_tag, checkpoint_hints_json, fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required, is_intro)
        )
        return cursor.lastrowid


def delete_subtask(subtask_id):
    """Delete a subtask."""
    with db_session() as conn:
        conn.execute("DELETE FROM subtask WHERE id = ?", (subtask_id,))


def update_subtasks(task_id, subtasks_list, estimated_minutes_list=None, quiz_json_list=None,
                    path_list=None, path_model_list=None, graded_artifact_json_list=None,
                    fertig_wenn_list=None, tipps_list=None, checkpoint_type_list=None,
                    kern_standard_tag_list=None, checkpoint_hints_list=None, school_only_list=None,
                    fork_group_list=None, fork_branch_list=None, fork_branch_label_list=None,
                    fork_branch_note_list=None, fork_required_list=None):
    """Update subtasks for a task in-place by position.

    UPDATEs existing subtasks at matching positions (preserves their IDs and thus
    student_subtask completion records). INSERTs new positions, DELETEs removed ones.
    Material assignments are preserved for existing subtasks automatically.
    """
    with db_session() as conn:
        # Load existing subtasks keyed by position
        old_rows = conn.execute(
            "SELECT * FROM subtask WHERE task_id = ? ORDER BY reihenfolge", (task_id,)
        ).fetchall()
        old_by_pos = {r['reihenfolge']: dict(r) for r in old_rows}

        new_positions = set()

        for i, beschreibung in enumerate(subtasks_list):
            if not beschreibung.strip():
                continue
            new_positions.add(i)

            # Parse all fields from parallel lists
            estimated_minutes = None
            if estimated_minutes_list and i < len(estimated_minutes_list):
                try:
                    minutes = estimated_minutes_list[i].strip()
                    estimated_minutes = int(minutes) if minutes else None
                except (ValueError, AttributeError):
                    pass

            subtask_quiz = None
            if quiz_json_list and i < len(quiz_json_list):
                qj = quiz_json_list[i].strip() if quiz_json_list[i] else ''
                subtask_quiz = qj if qj else None

            path = None
            if path_list and i < len(path_list):
                p = path_list[i].strip() if path_list[i] else ''
                path = p if p else None

            path_model = 'skip'
            if path_model_list and i < len(path_model_list):
                pm = path_model_list[i].strip() if path_model_list[i] else ''
                path_model = pm if pm in ('skip', 'depth') else 'skip'

            graded_artifact = None
            if graded_artifact_json_list and i < len(graded_artifact_json_list):
                ga = graded_artifact_json_list[i].strip() if graded_artifact_json_list[i] else ''
                graded_artifact = ga if ga else None

            fertig_wenn = None
            if fertig_wenn_list and i < len(fertig_wenn_list):
                fw = fertig_wenn_list[i].strip() if fertig_wenn_list[i] else ''
                fertig_wenn = fw if fw else None

            tipps = None
            if tipps_list and i < len(tipps_list):
                tp = tipps_list[i].strip() if tipps_list[i] else ''
                tipps = tp if tp else None

            checkpoint_type = None
            if checkpoint_type_list and i < len(checkpoint_type_list):
                ct = checkpoint_type_list[i].strip() if checkpoint_type_list[i] else ''
                checkpoint_type = ct if ct in ('quiz', 'abnahme', 'artefakt') else None

            kern_standard_tag = None
            if kern_standard_tag_list and i < len(kern_standard_tag_list):
                kst = kern_standard_tag_list[i].strip() if kern_standard_tag_list[i] else ''
                kern_standard_tag = kst if kst in ('kern', 'standard') else None

            checkpoint_hints = None
            if checkpoint_hints_list and i < len(checkpoint_hints_list):
                lines = [l.strip() for l in (checkpoint_hints_list[i] or '').splitlines() if l.strip()]
                checkpoint_hints = json.dumps(lines, ensure_ascii=False) if lines else None

            school_only = 0
            if school_only_list and i < len(school_only_list):
                school_only = 1 if school_only_list[i] == '1' else 0

            fork_group = None
            if fork_group_list and i < len(fork_group_list):
                fg = fork_group_list[i].strip() if fork_group_list[i] else ''
                fork_group = fg if fg else None

            fork_branch = None
            if fork_branch_list and i < len(fork_branch_list):
                fb = fork_branch_list[i].strip() if fork_branch_list[i] else ''
                fork_branch = fb if fb else None

            fork_branch_label = None
            if fork_branch_label_list and i < len(fork_branch_label_list):
                fbl = fork_branch_label_list[i].strip() if fork_branch_label_list[i] else ''
                fork_branch_label = fbl if fbl else None

            fork_branch_note = None
            if fork_branch_note_list and i < len(fork_branch_note_list):
                fbn = fork_branch_note_list[i].strip() if fork_branch_note_list[i] else ''
                fork_branch_note = fbn if fbn else None

            fork_required = 1
            if fork_required_list and i < len(fork_required_list):
                fork_required = 1 if fork_required_list[i] == '1' else 0

            if i in old_by_pos:
                # UPDATE in-place — preserves subtask ID and student_subtask records
                conn.execute("""
                    UPDATE subtask SET beschreibung=?, estimated_minutes=?,
                    quiz_json=?, path=?, path_model=?, graded_artifact_json=?,
                    fertig_wenn=?, tipps=?, checkpoint_type=?, kern_standard_tag=?,
                    checkpoint_hints_json=?, school_only=?,
                    fork_group=?, fork_branch=?, fork_branch_label=?, fork_branch_note=?, fork_required=?
                    WHERE id=?
                """, (beschreibung.strip(), estimated_minutes, subtask_quiz,
                      path, path_model, graded_artifact, fertig_wenn, tipps,
                      checkpoint_type, kern_standard_tag, checkpoint_hints, school_only,
                      fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required,
                      old_by_pos[i]['id']))
            else:
                # INSERT new subtask at this position
                conn.execute(
                    "INSERT INTO subtask (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json, path, path_model, graded_artifact_json, fertig_wenn, tipps, checkpoint_type, kern_standard_tag, checkpoint_hints_json, school_only, fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (task_id, beschreibung.strip(), i, estimated_minutes, subtask_quiz,
                     path, path_model, graded_artifact, fertig_wenn, tipps,
                     checkpoint_type, kern_standard_tag, checkpoint_hints, school_only,
                     fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required)
                )

        # DELETE subtasks at positions no longer present
        for old_pos, old_sub in old_by_pos.items():
            if old_pos not in new_positions:
                sub_id = old_sub['id']
                # Orphan quiz_attempt references before deleting
                conn.execute("UPDATE quiz_attempt SET subtask_id = NULL WHERE subtask_id = ?", (sub_id,))
                conn.execute("DELETE FROM material_subtask WHERE subtask_id = ?", (sub_id,))
                conn.execute("DELETE FROM subtask WHERE id = ?", (sub_id,))


def update_subtasks_from_import(task_id, subtasks_data):
    """Update subtasks in-place by position to preserve student progress.

    Unlike update_subtasks() which deletes and recreates all subtasks,
    this function UPDATEs existing subtasks at matching positions so that
    student_subtask foreign keys (and thus completion status) survive.

    Args:
        task_id: The task to update subtasks for
        subtasks_data: List of subtask dicts from import JSON (with keys:
            beschreibung, reihenfolge, estimated_minutes, quiz, path, path_model,
            graded_artifact)

    Returns:
        dict mapping reihenfolge -> subtask_id for the new state
    """
    with db_session() as conn:
        # Get old subtasks keyed by position
        old_rows = conn.execute(
            "SELECT * FROM subtask WHERE task_id = ? ORDER BY reihenfolge",
            (task_id,)
        ).fetchall()
        old_by_pos = {r['reihenfolge']: dict(r) for r in old_rows}

        new_positions = set()
        subtask_id_by_position = {}

        for i, sub in enumerate(subtasks_data):
            pos = sub.get('reihenfolge', i)
            new_positions.add(pos)
            quiz_json = json.dumps(sub['quiz'], ensure_ascii=False) if sub.get('quiz') else None
            ga_json = json.dumps(sub['graded_artifact'], ensure_ascii=False) if sub.get('graded_artifact') else None
            gate_json = json.dumps(sub['artifact_gate'], ensure_ascii=False) if sub.get('artifact_gate') else None
            path = sub.get('path')
            path_model = sub.get('path_model', 'skip')
            estimated_minutes = sub.get('estimated_minutes')

            fertig_wenn = sub.get('fertig_wenn') or None
            tipps = sub.get('tipps') or None
            checkpoint_type = sub.get('checkpoint_type') or None
            kern_standard_tag = sub.get('kern_standard_tag') or None
            checkpoint_hints = json.dumps(sub['checkpoint_hints'], ensure_ascii=False) if sub.get('checkpoint_hints') else None
            fork_group = sub.get('fork_group') or None
            fork_branch = sub.get('fork_branch') or None
            fork_branch_label = sub.get('fork_branch_label') or None
            fork_branch_note = sub.get('fork_branch_note') or None
            fork_required = 1 if sub.get('fork_required', True) else 0
            is_intro = 1 if sub.get('is_intro') else 0

            if pos in old_by_pos:
                # UPDATE existing subtask — keeps the ID, preserves student_subtask
                sub_id = old_by_pos[pos]['id']
                conn.execute("""
                    UPDATE subtask SET beschreibung=?, estimated_minutes=?,
                    quiz_json=?, path=?, path_model=?, graded_artifact_json=?, artifact_gate_json=?,
                    fertig_wenn=?, tipps=?, checkpoint_type=?, kern_standard_tag=?,
                    checkpoint_hints_json=?,
                    fork_group=?, fork_branch=?, fork_branch_label=?, fork_branch_note=?, fork_required=?,
                    is_intro=?
                    WHERE id=?
                """, (sub['beschreibung'], estimated_minutes, quiz_json,
                      path, path_model, ga_json, gate_json, fertig_wenn, tipps,
                      checkpoint_type, kern_standard_tag, checkpoint_hints,
                      fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required,
                      is_intro, sub_id))
                subtask_id_by_position[pos] = sub_id
            else:
                # INSERT new subtask at this position
                cursor = conn.execute(
                    "INSERT INTO subtask (task_id, beschreibung, reihenfolge, estimated_minutes, quiz_json, path, path_model, graded_artifact_json, artifact_gate_json, fertig_wenn, tipps, checkpoint_type, kern_standard_tag, checkpoint_hints_json, fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required, is_intro) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (task_id, sub['beschreibung'], pos, estimated_minutes, quiz_json, path, path_model, ga_json, gate_json, fertig_wenn, tipps,
                     checkpoint_type, kern_standard_tag, checkpoint_hints,
                     fork_group, fork_branch, fork_branch_label, fork_branch_note, fork_required, is_intro)
                )
                subtask_id_by_position[pos] = cursor.lastrowid

        # Delete old subtasks at positions no longer present
        for old_pos, old_sub in old_by_pos.items():
            if old_pos not in new_positions:
                old_id = old_sub['id']
                # Orphan quiz_attempt references
                conn.execute("UPDATE quiz_attempt SET subtask_id = NULL WHERE subtask_id = ?", (old_id,))
                # Delete student_subtask (task no longer exists)
                conn.execute("DELETE FROM student_subtask WHERE subtask_id = ?", (old_id,))
                # Delete warmup_history
                conn.execute("DELETE FROM warmup_history WHERE subtask_id = ?", (old_id,))
                # Delete material assignments
                conn.execute("DELETE FROM material_subtask WHERE subtask_id = ?", (old_id,))
                # Delete the subtask itself
                conn.execute("DELETE FROM subtask WHERE id = ?", (old_id,))

        return subtask_id_by_position


# ============ Material functions ============

def get_materials(task_id):
    """Get materials for a task."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM material WHERE task_id = ?",
            (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_external_link_domains():
    """Distinct domains referenced by material links, with usage count and the
    topic names that use them — for building a school-firewall whitelist."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT m.pfad, t.name AS task_name
            FROM material m
            JOIN task t ON m.task_id = t.id
            WHERE m.typ = 'link' AND m.pfad != ''
        ''').fetchall()

    domains = {}
    for row in rows:
        domain = urlparse(row['pfad']).netloc
        if not domain:
            continue
        # UCS@school's Internetregeln docs recommend the bare domain
        # (e.g. "wikipedia.org") over the "www." form, since it matches subdomains too.
        if domain.startswith('www.'):
            domain = domain[4:]
        entry = domains.setdefault(domain, {'count': 0, 'themen': set()})
        entry['count'] += 1
        entry['themen'].add(row['task_name'])

    result = [
        {'domain': domain, 'count': data['count'], 'themen': sorted(data['themen'])}
        for domain, data in domains.items()
    ]
    result.sort(key=lambda d: d['domain'])
    return result


def get_material(material_id):
    """Get a single material by ID."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM material WHERE id = ?",
            (material_id,)
        ).fetchone()
        return dict(row) if row else None


def create_material(task_id, typ, pfad, beschreibung='', attribution=None, school_only=False):
    """Create a material."""
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO material (task_id, typ, pfad, beschreibung, attribution, school_only) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, typ, pfad, beschreibung, attribution, 1 if school_only else 0)
        )
        return cursor.lastrowid


def update_material_attribution(material_id, attribution):
    """Update a material's attribution credit."""
    with db_session() as conn:
        conn.execute(
            "UPDATE material SET attribution = ? WHERE id = ?",
            (attribution, material_id)
        )


def update_material_school_only(material_id, school_only):
    """Update whether a material is restricted to the school network (network gate)."""
    with db_session() as conn:
        conn.execute(
            "UPDATE material SET school_only = ? WHERE id = ?",
            (1 if school_only else 0, material_id)
        )


def delete_material(material_id):
    """Delete a material."""
    with db_session() as conn:
        conn.execute("DELETE FROM material WHERE id = ?", (material_id,))


def update_material_beschreibung(material_id, beschreibung):
    with db_session() as conn:
        conn.execute("UPDATE material SET beschreibung = ? WHERE id = ?", (beschreibung, material_id))


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
        

def get_practice_unlocked_task_ids(klasse_id):
    """Return set of task_ids unlocked for practice in this class."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT task_id FROM class_practice_unlock WHERE klasse_id = ?",
            (klasse_id,)
        ).fetchall()
    return {r['task_id'] for r in rows}


def set_practice_unlock_for_class(klasse_id, task_id, unlocked):
    """Insert or delete a class_practice_unlock row for this class+topic."""
    with db_session() as conn:
        if unlocked:
            conn.execute(
                "INSERT OR IGNORE INTO class_practice_unlock (klasse_id, task_id) VALUES (?, ?)",
                (klasse_id, task_id)
            )
        else:
            conn.execute(
                "DELETE FROM class_practice_unlock WHERE klasse_id = ? AND task_id = ?",
                (klasse_id, task_id)
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
    """Get list of subtasks visible to a student based on learning path.

    If student has a learning path (lernpfad):
      - Return ALL subtasks (ordered), each with a 'required' flag
      - Filter out hidden subtasks (hidden=1)
    If no path (legacy): fall back to subtask_visibility query.

    Args:
        student_id: The student ID
        klasse_id: The class ID the student is viewing the task in
        task_id: The task ID

    Returns:
        List of subtask dicts that are visible to this student.
        Each dict has an added 'required' key (True/False) when path-based.
    """
    with db_session() as conn:
        # Check if student has a learning path
        student_row = conn.execute(
            "SELECT lernpfad FROM student WHERE id = ?", (student_id,)
        ).fetchone()
        student_path = student_row['lernpfad'] if student_row else None

        if student_path and student_path in VALID_PATHS:
            # Path-based: return all non-hidden subtasks with required flag
            rows = conn.execute('''
                SELECT * FROM subtask
                WHERE task_id = ? AND COALESCE(hidden, 0) = 0
                ORDER BY reihenfolge
            ''', (task_id,)).fetchall()
            subtasks = [dict(r) for r in rows]
            # If the topic is a pure Seilbahn topic, treat all its tasks as required
            # regardless of the student's global lernpfad — they were assigned this topic.
            all_seilbahn = subtasks and all(s.get('path') == 'seilbahn' for s in subtasks)
            effective_path = 'seilbahn' if all_seilbahn else student_path
            result = []
            for d in subtasks:
                d['required'] = is_subtask_required_for_path(d, effective_path)
                result.append(d)
            return _filter_fork_subtasks(result, student_id)
        else:
            # Legacy fallback: subtask_visibility query
            rows = conn.execute('''
                SELECT s.* FROM subtask s
                WHERE s.task_id = ?
                AND s.id IN (
                    SELECT sv.subtask_id FROM subtask_visibility sv
                    WHERE sv.student_id = ? AND sv.enabled = 1
                    UNION
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
            result = []
            for r in rows:
                d = dict(r)
                d['required'] = True  # Legacy: all visible = required
                result.append(d)
            return _filter_fork_subtasks(result, student_id)


_IS_SEILBAHN_SQL = """
    CASE WHEN (SELECT COUNT(*) FROM subtask WHERE task_id = t.id) > 0
              AND (SELECT COUNT(*) FROM subtask WHERE task_id = t.id AND path != 'seilbahn') = 0
    THEN 1 ELSE 0 END as is_seilbahn
"""


def get_student_task(student_id, klasse_id):
    """Get student's active primary topic for a class."""
    with db_session() as conn:
        row = conn.execute(f'''
            SELECT st.*, t.name, t.beschreibung, t.lernziel, t.fach, t.stufe, t.kategorie, t.quiz_json, t.why_learn_this, t.subtask_quiz_required,
                t.unit_slug, t.connections_json,
                {_IS_SEILBAHN_SQL}
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
        rows = conn.execute(f'''
            SELECT st.*, t.name, t.beschreibung, t.lernziel, t.fach, t.stufe, t.kategorie, t.quiz_json, t.why_learn_this, t.subtask_quiz_required,
                t.unit_slug, t.connections_json,
                {_IS_SEILBAHN_SQL}
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.student_id = ? AND st.klasse_id = ?
            ORDER BY st.abgeschlossen ASC, st.id DESC
        ''', (student_id, klasse_id)).fetchall()
        result = [dict(r) for r in rows]
    return result


def get_sidequests_for_klasse(klasse_id):
    """Get all active sidequests for students in a class."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT s.vorname, s.nachname, t.name AS task_name
            FROM student_task st
            JOIN student s ON st.student_id = s.id
            JOIN task t ON st.task_id = t.id
            WHERE st.klasse_id = ? AND st.rolle = 'sidequest' AND st.abgeschlossen = 0
            ORDER BY s.nachname, s.vorname
        ''', (klasse_id,)).fetchall()
        return [dict(r) for r in rows]


def get_student_sidequests(student_id, klasse_id):
    """Get active sidequests for a student in a class."""
    with db_session() as conn:
        rows = conn.execute(f'''
            SELECT st.*, t.name, t.beschreibung, t.fach, t.stufe, t.kategorie, t.quiz_json,
                {_IS_SEILBAHN_SQL}
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.student_id = ? AND st.klasse_id = ? AND st.rolle = 'sidequest' AND st.abgeschlossen = 0
            ORDER BY st.id DESC
        ''', (student_id, klasse_id)).fetchall()
        return [dict(r) for r in rows]


def get_student_subtask_progress(student_task_id):
    """Get subtask completion status for a student's task."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT sub.*, COALESCE(ss.erledigt, 0) as erledigt,
                   ss.artifact_gate_passed as artifact_gate_passed
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
        existing = conn.execute(
            'SELECT id, completed_at FROM student_subtask WHERE student_task_id = ? AND subtask_id = ?',
            (student_task_id, subtask_id)
        ).fetchone()
        now = datetime.now().strftime('%Y-%m-%d')
        if existing:
            # Preserve first completion timestamp; don't overwrite if already set
            new_completed_at = existing['completed_at'] or (now if erledigt else None)
            conn.execute(
                'UPDATE student_subtask SET erledigt = ?, completed_at = ? WHERE id = ?',
                (1 if erledigt else 0, new_completed_at, existing['id'])
            )
        else:
            conn.execute(
                'INSERT INTO student_subtask (student_task_id, subtask_id, erledigt, completed_at) VALUES (?, ?, ?, ?)',
                (student_task_id, subtask_id, 1 if erledigt else 0, now if erledigt else None)
            )

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
                # Check if quiz already passed (or, for Chemie Quiz-checkpoints,
                # a completed checkpoint session — any score, see has_passed_subtask_quiz)
                quiz_passed = conn.execute('''
                    SELECT 1 FROM quiz_attempt
                    WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
                    UNION
                    SELECT 1 FROM checkpoint_attempt
                    WHERE checkpoint_id = ? AND superseded_at IS NULL
                    AND student_id = (SELECT student_id FROM student_task WHERE id = ?)
                    LIMIT 1
                ''', (student_task_id, subtask_id, subtask_id, student_task_id)).fetchone()

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
                UNION
                SELECT 1 FROM checkpoint_attempt
                WHERE checkpoint_id = ? AND superseded_at IS NULL
                AND student_id = (SELECT student_id FROM student_task WHERE id = ?)
                LIMIT 1
            ''', (student_task_id, subtask_id, subtask_id, student_task_id)).fetchone()
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


def save_artifact_gate_result(student_task_id: int, subtask_id: int, passed: bool):
    """Persist the deterministic gate check result for a student's subtask."""
    with db_session() as conn:
        existing = conn.execute(
            'SELECT id FROM student_subtask WHERE student_task_id = ? AND subtask_id = ?',
            (student_task_id, subtask_id)
        ).fetchone()
        val = 1 if passed else 0
        if existing:
            conn.execute(
                'UPDATE student_subtask SET artifact_gate_passed = ? WHERE id = ?',
                (val, existing['id'])
            )
        else:
            conn.execute(
                'INSERT INTO student_subtask (student_task_id, subtask_id, erledigt, artifact_gate_passed) VALUES (?, ?, 0, ?)',
                (student_task_id, subtask_id, val)
            )



def log_artifact_gate_attempt(student_id: int, subtask_id: int, passed: bool, details: list, timezone: str = 'Europe/Berlin'):
    """Append one gate check attempt with its failed criteria list."""
    import json as _json
    # Was the only place doing its own pytz dance, with a utcnow() fallback that
    # silently relabelled the row 'UTC'. now_local() is the single time basis now.
    ts = now_local()
    with db_session() as conn:
        conn.execute(
            'INSERT INTO artifact_gate_attempt (student_id, subtask_id, timestamp_local, timezone, passed, details_json) VALUES (?, ?, ?, ?, ?, ?)',
            (student_id, subtask_id, ts, timezone, 1 if passed else 0, _json.dumps(details, ensure_ascii=False))
        )


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

    Complete = all required subtasks erledigt + all required subtask quizzes passed
               + topic quiz passed (or no topic quiz).
    Only path-required subtasks count toward completion.
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

        # A pending (unresolved) fork blocks completion even if every currently
        # visible subtask is done — its subtasks aren't in the visible list yet.
        if get_pending_fork_groups(task_id, student_id):
            return False

        # Get visible subtasks (with path-based required flag)
        visible_subtasks = get_visible_subtasks_for_student(student_id, klasse_id, task_id)
        # Only check required subtasks for completion
        required_subtasks = [s for s in visible_subtasks if s.get('required', True)]
        required_ids = [s['id'] for s in required_subtasks]

        if required_ids:
            placeholders = ','.join('?' * len(required_ids))
            subtask_rows = conn.execute(f'''
                SELECT sub.id, sub.quiz_json, COALESCE(ss.erledigt, 0) as erledigt
                FROM subtask sub
                LEFT JOIN student_subtask ss ON sub.id = ss.subtask_id AND ss.student_task_id = ?
                WHERE sub.id IN ({placeholders})
            ''', [student_task_id] + required_ids).fetchall()

            quiz_required = task_info and task_info['subtask_quiz_required']

            for sub in subtask_rows:
                if not sub['erledigt']:
                    return False
                # Check subtask quiz if required
                if quiz_required and sub['quiz_json']:
                    quiz_passed = conn.execute('''
                        SELECT 1 FROM quiz_attempt
                        WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
                        UNION
                        SELECT 1 FROM checkpoint_attempt
                        WHERE checkpoint_id = ? AND superseded_at IS NULL
                        AND student_id = (SELECT student_id FROM student_task WHERE id = ?)
                        LIMIT 1
                    ''', (student_task_id, sub['id'], sub['id'], student_task_id)).fetchone()
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
                return False

        return True


# ============ Quiz functions ============

def save_quiz_attempt(student_task_id, punkte, max_punkte, antworten_json, subtask_id=None, quiz_snapshot=None):
    """Save a quiz attempt. subtask_id=None means topic-level quiz.
    quiz_snapshot: full quiz JSON string at attempt time, for accurate stats lookup.
    """
    min_punkte = max(1, int(max_punkte * 0.7)) if max_punkte > 0 else 1
    bestanden = punkte >= min_punkte if max_punkte > 0 else False
    with db_session() as conn:
        cursor = conn.execute('''
            INSERT INTO quiz_attempt (student_task_id, subtask_id, punkte, max_punkte, bestanden, antworten_json, quiz_snapshot_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (student_task_id, subtask_id, punkte, max_punkte, 1 if bestanden else 0, antworten_json,
              quiz_snapshot, now_local()))
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
    """Returns True if this subtask's quiz gate is cleared: a passed quiz_attempt,
    or — for Chemie Quiz-checkpoints, which log to checkpoint_attempt instead —
    any completed checkpoint session (any score; the 0/2/3 Kern-gate is a separate
    Chemie-side grading query, not a Lernmanager progression gate)."""
    with db_session() as conn:
        row = conn.execute('''
            SELECT 1 FROM quiz_attempt
            WHERE student_task_id = ? AND subtask_id = ? AND bestanden = 1
            LIMIT 1
        ''', (student_task_id, subtask_id)).fetchone()
        if row is not None:
            return True
        row = conn.execute('''
            SELECT 1 FROM checkpoint_attempt
            WHERE checkpoint_id = ? AND superseded_at IS NULL
            AND student_id = (SELECT student_id FROM student_task WHERE id = ?)
            LIMIT 1
        ''', (subtask_id, student_task_id)).fetchone()
        return row is not None


# ============ Checkpoint-Punktekonto (Chemie 11/12) ============

def create_checkpoint_attempt(student_id, checkpoint_id, module_id, checkpoint_type,
                               kern_standard_tag, score, attempt_count=1, hint_count=0,
                               timestamp=None, needs_review=False, review_notes=None,
                               quiz_snapshot_json=None, session_uid=None):
    """Log one completed Chemie checkpoint. One row per completion, not per submission
    (retries live in attempt_count/hint_count). See docs/shared/lernmanager/chemie-data-contract.md.

    needs_review/review_notes: set when the session contains a question that was
    given up on only because LLM grading was unavailable (not a real give-up) --
    flags the row for a teacher to re-grade by hand.

    quiz_snapshot_json: the checkpoint's quiz_json as it was at completion time --
    content can be edited later, so this is what makes a future review UI show the
    question actually answered, not whatever the Aufgabe says today.

    session_uid: if given, backfills checkpoint_answer rows written during this
    session (checkpoint_attempt_id was NULL until this row existed) -- see
    create_checkpoint_answer.
    """
    with db_session() as conn:
        cursor = conn.execute('''
            INSERT INTO checkpoint_attempt
            (student_id, checkpoint_id, module_id, checkpoint_type, kern_standard_tag,
             score, attempt_count, hint_count, timestamp, needs_review, review_notes,
             quiz_snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, ?), ?, ?, ?)
        ''', (student_id, checkpoint_id, module_id, checkpoint_type, kern_standard_tag,
              score, attempt_count, hint_count, timestamp, now_local(), 1 if needs_review else 0, review_notes,
              quiz_snapshot_json))
        attempt_id = cursor.lastrowid
        if session_uid:
            conn.execute('''
                UPDATE checkpoint_answer SET checkpoint_attempt_id = ?
                WHERE session_uid = ? AND checkpoint_attempt_id IS NULL
            ''', (attempt_id, session_uid))
        return attempt_id


def create_checkpoint_answer(student_id, checkpoint_id, session_uid, question_index,
                              attempt_no, answer_text, correct, feedback, grader,
                              llm_model=None, hints_used_before=0, gave_up=False,
                              prompt_version=None):
    """Log one graded attempt at one checkpoint question -- the per-question detail
    checkpoint_attempt never captured (see migrate_047). Written as answers happen,
    before checkpoint_attempt exists (checkpoint_attempt_id starts NULL and is
    backfilled by create_checkpoint_attempt via session_uid once the session ends).

    correct: True/False/None (None = LLM grading failed, matches the strict=True
    contract in llm_grading.grade_answer -- don't collapse to False, that would
    misrepresent an ungraded attempt as a wrong one in a future review UI).

    prompt_version: which system prompt graded this (migrate_048), None when no LLM
    was involved (exact match / MC / give-up).
    """
    with db_session() as conn:
        conn.execute('''
            INSERT INTO checkpoint_answer
            (student_id, checkpoint_id, session_uid, question_index, attempt_no,
             answer_text, correct, feedback, grader, llm_model, hints_used_before,
             gave_up, timestamp, prompt_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, checkpoint_id, session_uid, question_index, attempt_no,
              answer_text, correct, feedback, grader, llm_model, hints_used_before,
              1 if gave_up else 0, now_local(), prompt_version))


def get_checkpoint_attempts_for_student(student_id, module_id=None, include_superseded=False):
    """Get a student's checkpoint attempts, newest first. module_id narrows to one Thema.

    include_superseded: superseded rows (see reset_student_progress_for_task) are
    excluded by default -- they're the pre-reset grade record, not the current one.
    A review UI can pass True to show them as history.
    """
    superseded_clause = '' if include_superseded else 'AND superseded_at IS NULL'
    with db_session() as conn:
        if module_id is not None:
            rows = conn.execute(f'''
                SELECT * FROM checkpoint_attempt WHERE student_id = ? AND module_id = ? {superseded_clause}
                ORDER BY timestamp DESC
            ''', (student_id, module_id)).fetchall()
        else:
            rows = conn.execute(f'''
                SELECT * FROM checkpoint_attempt WHERE student_id = ? {superseded_clause}
                ORDER BY timestamp DESC
            ''', (student_id,)).fetchall()
        return [dict(r) for r in rows]


def get_latest_checkpoint_attempt(student_id, checkpoint_id):
    """The student's most recent live session for one checkpoint, or None.

    Powers the review banner a student sees when they reopen a checkpoint they
    have already completed. Superseded rows are excluded: after a progress reset
    they are history, and showing a stale grade as current would be wrong.
    """
    with db_session() as conn:
        row = conn.execute("""
            SELECT * FROM checkpoint_attempt
            WHERE student_id = ? AND checkpoint_id = ? AND superseded_at IS NULL
            ORDER BY timestamp DESC LIMIT 1
        """, (student_id, checkpoint_id)).fetchone()
        return dict(row) if row else None


def get_reopened_checkpoint_notice(student_id, checkpoint_id):
    """The reset that reopened this checkpoint, so the student can be told why.

    Counterpart to get_latest_checkpoint_attempt: that one hides superseded rows,
    which left a reset completely silent -- the result and the teacher's
    student_feedback vanished from the student's view with no explanation. This
    reads the newest superseded row purely to surface that message.

    Returns the feedback and the reset time only. Deliberately not the old score:
    it no longer counts, and repeating an annulled grade above a retake gives the
    student a number to fixate on instead of the note telling them what to fix.

    Call only when there is no live attempt -- once the retake lands, that session
    carries its own review banner and this notice is stale.
    """
    with db_session() as conn:
        row = conn.execute("""
            SELECT student_feedback, superseded_at FROM checkpoint_attempt
            WHERE student_id = ? AND checkpoint_id = ? AND superseded_at IS NOT NULL
            ORDER BY superseded_at DESC, id DESC LIMIT 1
        """, (student_id, checkpoint_id)).fetchone()
        if not row:
            return None
        return {'feedback': row['student_feedback'],
                'superseded_at': row['superseded_at']}


def get_checkpoint_answers_for_attempt(checkpoint_attempt_id):
    """All logged answer attempts for one completed checkpoint session, in the order
    they were submitted -- the per-question detail behind a checkpoint_attempt's
    aggregate score. For a future teacher-review UI."""
    with db_session() as conn:
        rows = conn.execute('''
            SELECT * FROM checkpoint_answer WHERE checkpoint_attempt_id = ?
            ORDER BY question_index, attempt_no
        ''', (checkpoint_attempt_id,)).fetchall()
        return [dict(r) for r in rows]


def effective_checkpoint_score(attempt):
    """The score that counts: the teacher's override if one exists, else the
    computed one (migrate_048).

    Every consumer of a checkpoint score -- review UI, exports, and whatever
    eventually computes the Kern-Sperre/Punktekonto -- must go through here rather
    than reading `score` directly, so "a teacher override wins" is stated once.
    """
    teacher_score = attempt.get('teacher_score')
    return attempt['score'] if teacher_score is None else teacher_score


def checkpoint_review_status(attempt):
    """What a STUDENT is told about a teacher's review of one session.

    Returns 'unreviewed' | 'confirmed' | 'changed'.

    'changed' is keyed on the score actually moving, not on teacher_score merely
    being set: a teacher who explicitly picks the same number the LLM computed has
    confirmed it, and telling the student it was "changed" would be a lie.

    Deliberately carries no timestamp -- students see THAT a session was checked,
    never when, so nobody can read a teacher's working hours off the page.
    """
    if not attempt.get('reviewed_at'):
        return 'unreviewed'
    return 'changed' if effective_checkpoint_score(attempt) != attempt['score'] else 'confirmed'


def get_checkpoint_reviews(klasse_id=None, student_id=None, date_from=None,
                           date_to=None, unreviewed_only=False, checkpoint_id=None,
                           include_superseded=False, limit=300):
    """Checkpoint sessions for the teacher-review UI, newest first.

    One row per completed checkpoint (checkpoint_attempt), enriched with the
    student/class/topic names needed to display and filter it.

    include_superseded: reset sessions (see supersede_checkpoint_attempts) are
    excluded by default -- they are the pre-reset grade record, not the current
    one. Pass True to show them as read-only history.

    date_from/date_to: 'YYYY-MM-DD' (inclusive). date_to is compared against the
    end of that day so a same-day filter is not empty.

    The subtask join is LEFT: checkpoint_id carries no FK on purpose (migrate_047),
    so an Aufgabe that has since been deleted must still list its results -- the
    display falls back to quiz_snapshot_json.
    """
    sql = '''
        SELECT ca.*,
               s.vorname, s.nachname,
               t.name as task_name,
               sub.beschreibung as subtask_name,
               sub.reihenfolge as subtask_position
        FROM checkpoint_attempt ca
        JOIN student s ON ca.student_id = s.id
        LEFT JOIN task t ON ca.module_id = t.id
        LEFT JOIN subtask sub ON ca.checkpoint_id = sub.id
        WHERE 1 = 1
    '''
    params = []
    if not include_superseded:
        sql += ' AND ca.superseded_at IS NULL'
    if checkpoint_id:
        sql += ' AND ca.checkpoint_id = ?'
        params.append(checkpoint_id)
    if klasse_id:
        # Class membership is many-to-many and lives outside checkpoint_attempt,
        # so it is an EXISTS rather than a join -- a student in two classes must
        # not make their checkpoints appear twice.
        sql += ''' AND EXISTS (SELECT 1 FROM student_klasse sk
                                WHERE sk.student_id = ca.student_id AND sk.klasse_id = ?)'''
        params.append(klasse_id)
    if student_id:
        sql += ' AND ca.student_id = ?'
        params.append(student_id)
    if date_from:
        sql += ' AND ca.timestamp >= ?'
        params.append(f'{date_from} 00:00:00')
    if date_to:
        sql += ' AND ca.timestamp <= ?'
        params.append(f'{date_to} 23:59:59')
    if unreviewed_only:
        # "Dealt with" is either a grade override or an explicit review mark. It
        # used to be the score alone, which predates reviewed_at (migrate_049) and
        # left two states stuck in the queue forever: "I looked and the LLM was
        # right" (the most common review outcome, and the state migrate_049 exists
        # to make storable), and a session checked off without a grade change.
        # Widened, not swapped -- anything the old condition hid stays hidden.
        sql += ' AND ca.teacher_score IS NULL AND ca.reviewed_at IS NULL'
    sql += ' ORDER BY ca.timestamp DESC LIMIT ?'
    params.append(limit)

    with db_session() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for row in rows:
        row['effective_score'] = effective_checkpoint_score(row)
        row['student_name'] = f"{row['vorname']} {row['nachname']}"
    return rows


def get_checkpoint_students():
    """Students who actually have checkpoint results, for the review page's filter.

    Deliberately not "all students": the dropdown should offer the handful of
    people there is something to review for, not the whole school.
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT DISTINCT s.id, s.vorname, s.nachname
            FROM checkpoint_attempt ca
            JOIN student s ON ca.student_id = s.id
            WHERE ca.superseded_at IS NULL
            ORDER BY s.nachname, s.vorname
        ''').fetchall()
    return [dict(r) for r in rows]


def get_checkpoint_checkpoints():
    """Checkpoints that actually have results, for the review page's filter.

    Same reasoning as get_checkpoint_students: offer the handful of checkpoints
    there is something to look at, not every Aufgabe in the database. Superseded
    rows count too -- a checkpoint whose only sessions were reset must stay
    selectable, otherwise its history becomes unreachable from the UI.
    """
    with db_session() as conn:
        rows = conn.execute('''
            SELECT ca.checkpoint_id AS id,
                   t.name AS task_name,
                   sub.beschreibung AS subtask_name,
                   sub.reihenfolge AS subtask_position,
                   COUNT(*) AS session_count
            FROM checkpoint_attempt ca
            LEFT JOIN task t ON ca.module_id = t.id
            LEFT JOIN subtask sub ON ca.checkpoint_id = sub.id
            GROUP BY ca.checkpoint_id
            ORDER BY t.name, sub.reihenfolge
        ''').fetchall()
    return [dict(r) for r in rows]


def supersede_checkpoint_attempts(attempt_ids):
    """Reopen checkpoint sessions for another try, without destroying the record.

    Sets superseded_at instead of deleting: the row, its teacher review and all
    its checkpoint_answer detail stay in the database as history. Every gate and
    listing filters superseded_at IS NULL, so the progression lock lifts and the
    student can take the checkpoint again -- their new session is written as a
    fresh row alongside the old one, not on top of it.

    Deliberately does NOT touch student_subtask: the Aufgabe was still done, only
    its checkpoint reopens. And deliberately does not un-complete the Thema -- a
    student may have moved on to the next topic in the queue, and forcing a second
    active topic would violate idx_one_active_primary. check_task_completion marks
    it complete again once the retake lands.

    Already-superseded rows are skipped, so the first reset's timestamp survives a
    double click. Returns the number of sessions actually reopened.
    """
    ids = [int(i) for i in attempt_ids]
    if not ids:
        return 0
    placeholders = ','.join('?' * len(ids))
    with db_session() as conn:
        cursor = conn.execute(f'''
            UPDATE checkpoint_attempt SET superseded_at = ?
            WHERE id IN ({placeholders}) AND superseded_at IS NULL
        ''', [now_local()] + ids)
        return cursor.rowcount


def get_checkpoint_answers_for_attempts(attempt_ids):
    """All logged answers for several checkpoint sessions at once, grouped by
    attempt id. Batched deliberately: the review UI renders up to `limit` sessions
    and a per-session query would mean hundreds of round trips.
    """
    if not attempt_ids:
        return {}
    placeholders = ','.join('?' * len(attempt_ids))
    with db_session() as conn:
        rows = conn.execute(f'''
            SELECT * FROM checkpoint_answer
            WHERE checkpoint_attempt_id IN ({placeholders})
            ORDER BY question_index, attempt_no, id
        ''', list(attempt_ids)).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row['checkpoint_attempt_id'], []).append(dict(row))
    return grouped


def set_checkpoint_teacher_review(attempt_id, teacher_score, teacher_note,
                                  student_feedback, admin_id, reviewed=True):
    """Record the teacher's verdict on one checkpoint session (migrate_048/049).

    teacher_score None clears the override and hands the grade back to the computed
    score -- a teacher must be able to undo a correction, not only make one.

    `reviewed` is explicit rather than inferred from "did the teacher type
    anything". It used to be inferred, which made the most common review outcome
    impossible to express: reading a session, agreeing with the LLM and changing
    nothing left it indistinguishable from never having been opened. Students are
    now shown whether a session was checked (migrate_049), so "I looked and the
    machine was right" has to be a storable state.
    """
    with db_session() as conn:
        conn.execute('''
            UPDATE checkpoint_attempt
            SET teacher_score = ?, teacher_note = ?, student_feedback = ?,
                reviewed_at = CASE WHEN ? THEN ? ELSE NULL END,
                reviewed_by = CASE WHEN ? THEN ? ELSE NULL END
            WHERE id = ?
        ''', (teacher_score, teacher_note or None, student_feedback or None,
              1 if reviewed else 0, now_local(),
              1 if reviewed else 0, admin_id,
              attempt_id))


def bulk_correct_double_click_attempts(corrections, note, admin_id):
    """Apply the "without the double-click" score to many sessions at once.

    `corrections` is a list of (attempt_id, score) worked out by the caller from
    the same duplicate detection the review page shows -- this function does not
    re-derive it, so the teacher gets exactly the numbers that were on screen.

    Deliberately NOT set_checkpoint_teacher_review in a loop: that function writes
    student_feedback too, which would wipe every Rueckmeldung already written on
    the sessions being cleaned up. Here only the grade, the note and the review
    mark move.

    An existing teacher_note is never overwritten -- a teacher who already wrote
    their own reason for this session should keep it, the batch reason is only for
    the ones that had none.

    Returns the number of sessions changed.
    """
    if not corrections:
        return 0
    stamp = now_local()
    with db_session() as conn:
        changed = 0
        for attempt_id, score in corrections:
            cursor = conn.execute("""
                UPDATE checkpoint_attempt
                SET teacher_score = ?,
                    teacher_note = CASE
                        WHEN teacher_note IS NULL OR TRIM(teacher_note) = '' THEN ?
                        ELSE teacher_note END,
                    reviewed_at = ?, reviewed_by = ?
                WHERE id = ? AND superseded_at IS NULL
            """, (score, note, stamp, admin_id, int(attempt_id)))
            changed += cursor.rowcount
        return changed


def bulk_mark_double_click_reviewed(attempt_ids, note, admin_id):
    """Mark flagged sessions checked without touching the grade.

    The other half of bulk_correct_double_click_attempts. A session score is the
    min() across its questions (see app._score_checkpoint_session), so a
    double-click that lifts one question from 2 to 3 changes nothing when another
    question scored 0 or needed a hint -- which is the common case, not the edge
    one. Those sessions have no correction to apply but still sit in the teacher's
    open queue with a Doppelklick badge on them.

    So: the note and the review mark, never a score. Reversible per session with
    "Prüfung zurücknehmen", same as any other review.

    Already-reviewed and superseded rows are skipped -- the first is out of the
    queue already, the second no longer counts.
    """
    ids = [int(i) for i in attempt_ids]
    if not ids:
        return 0
    placeholders = ','.join('?' * len(ids))
    with db_session() as conn:
        cursor = conn.execute(f"""
            UPDATE checkpoint_attempt
            SET teacher_note = CASE
                    WHEN teacher_note IS NULL OR TRIM(teacher_note) = '' THEN ?
                    ELSE teacher_note END,
                reviewed_at = ?, reviewed_by = ?
            WHERE id IN ({placeholders})
              AND superseded_at IS NULL
              AND reviewed_at IS NULL
        """, [note, now_local(), admin_id] + ids)
        return cursor.rowcount


def bulk_note_checkpoint_answers(answer_ids, note):
    """Write the prompt-tuning note onto the answers flagged as double-clicks.

    Only the note. teacher_verdict stays untouched on purpose: it answers "was the
    KI's judgement right?", and a double-click is not a grading error -- the KI
    usually judged the resend correctly, the damage was the extra attempt. Filling
    in a verdict here would put non-grading noise into the calibration data the
    field exists to collect.

    Existing notes are kept, same reasoning as bulk_correct_double_click_attempts.
    """
    ids = [int(i) for i in answer_ids]
    if not ids:
        return 0
    placeholders = ','.join('?' * len(ids))
    with db_session() as conn:
        cursor = conn.execute(f"""
            UPDATE checkpoint_answer
            SET teacher_note = ?
            WHERE id IN ({placeholders})
              AND (teacher_note IS NULL OR TRIM(teacher_note) = '')
        """, [note] + ids)
        return cursor.rowcount


def set_checkpoint_answer_verdict(answer_id, teacher_verdict, teacher_note):
    """Record what the teacher says one answer actually was (migrate_048).

    Calibration only: this never changes any score. Its whole purpose is that
    `teacher_verdict == 0` can be counted in the export to show where the grading
    prompt disagrees with the teacher.

    The value answers the admin UI's question "War die KI-Bewertung richtig?"
    (ja/nein) -- it does NOT record what the answer was. Anything deriving the
    answer's real correctness must invert `correct` when this is 0.
    """
    with db_session() as conn:
        conn.execute('''
            UPDATE checkpoint_answer SET teacher_verdict = ?, teacher_note = ?
            WHERE id = ?
        ''', (teacher_verdict, teacher_note or None, answer_id))


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


def _question_hash(q_def):
    """Stable 16-char hash of a question's identity for deduplication across quiz versions.

    Two questions are identical iff they have the same type, text, options (in order),
    and correct answers. A change to any of these produces a different hash and a
    separate stats row — intentional, since the stats genuinely differ. For
    ordering/matching the authored order and the pairs are what "correct answers"
    means, so editing either starts a new row.
    """
    qtype = q_def.get('type', 'multiple_choice')
    parts = [qtype, q_def.get('text', '')]
    if qtype == 'multiple_choice':
        parts.append(json.dumps(q_def.get('options', []), ensure_ascii=False))
        parts.append(json.dumps(sorted(q_def.get('correct', []))))
    elif qtype == 'fill_blank':
        parts.append(json.dumps(sorted(a.lower() for a in q_def.get('answers', []))))
    elif qtype == 'ordering':
        parts.append(json.dumps(q_def.get('items', []), ensure_ascii=False))
    elif qtype == 'matching':
        parts.append(json.dumps(q_def.get('pairs', []), ensure_ascii=False))
        parts.append(json.dumps(sorted(str(d) for d in q_def.get('distractors', [])), ensure_ascii=False))
    else:
        parts.append(q_def.get('rubric', ''))
    return sha256('|'.join(parts).encode()).hexdigest()[:16]


def get_quiz_stats_by_topic(klasse_id=None, task_id=None, only_attempted=True, for_export=False):
    """Aggregate quiz attempt stats grouped by topic → subtask (by position) → question.

    Buckets answers by question hash (not index), using quiz_snapshot_json when available
    so stats reflect what students actually saw, even if the quiz was later edited.
    Old attempts without a snapshot fall back to the current quiz_json.

    Returns sorted list of topic dicts, each with sections (subtask quizzes first, topic quiz last).
    only_attempted=True omits topics/subtasks with no recorded attempts.
    """
    with db_session() as conn:
        sql = '''
            SELECT qa.antworten_json, qa.quiz_snapshot_json, qa.subtask_id,
                   st.task_id,
                   t.name AS task_name, t.quiz_json AS task_quiz_json,
                   sub.quiz_json AS subtask_quiz_json,
                   sub.reihenfolge AS subtask_reihenfolge
            FROM quiz_attempt qa
            JOIN student_task st ON qa.student_task_id = st.id
            JOIN task t ON st.task_id = t.id
            LEFT JOIN subtask sub ON qa.subtask_id = sub.id
            WHERE qa.antworten_json IS NOT NULL
        '''
        params = []
        if klasse_id:
            sql += ' AND st.klasse_id = ?'
            params.append(klasse_id)
        if task_id:
            sql += ' AND st.task_id = ?'
            params.append(task_id)
        attempt_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        extra_topics = extra_subs = []
        if not only_attempted:
            tp = [task_id] if task_id else []
            extra_topics = [dict(r) for r in conn.execute(
                'SELECT id, name, quiz_json FROM task WHERE quiz_json IS NOT NULL'
                + (' AND id = ?' if task_id else ''), tp).fetchall()]
            extra_subs = [dict(r) for r in conn.execute(
                'SELECT sub.id, sub.task_id, sub.quiz_json, sub.reihenfolge, t.name AS task_name'
                ' FROM subtask sub JOIN task t ON sub.task_id = t.id'
                ' WHERE sub.quiz_json IS NOT NULL'
                + (' AND sub.task_id = ?' if task_id else ''), tp).fetchall()]

    # sections: (task_id, subtask_id|None) -> {reihenfolge, is_topic_quiz, current_quiz_json, buckets}
    # buckets: question_hash -> {total, correct, answers, q_def}
    tasks_meta = {}
    sections = {}

    for row in attempt_rows:
        tid, sid = row['task_id'], row['subtask_id']
        tasks_meta.setdefault(tid, {'name': row['task_name'], 'quiz_json': row['task_quiz_json']})
        key = (tid, sid)
        if key not in sections:
            sections[key] = {
                'reihenfolge': row['subtask_reihenfolge'] if sid else 9999,
                'is_topic_quiz': sid is None,
                'current_quiz_json': row['subtask_quiz_json'] if sid else row['task_quiz_json'],
                'buckets': {},
            }

        try:
            antworten = json.loads(row['antworten_json'])
        except (json.JSONDecodeError, TypeError):
            continue

        # Prefer snapshot; fall back to current quiz_json for old attempts
        snapshot_str = row.get('quiz_snapshot_json') or (
            row['subtask_quiz_json'] if sid else row['task_quiz_json'])
        try:
            q_defs = json.loads(snapshot_str).get('questions', []) if snapshot_str else []
        except (json.JSONDecodeError, TypeError):
            q_defs = []

        for q_str, answer in antworten.items():
            if q_str == '_question_order':
                continue
            try:
                idx = int(q_str)
            except ValueError:
                continue
            q_def = q_defs[idx] if idx < len(q_defs) else None
            q_hash = _question_hash(q_def) if q_def else f'unknown_{idx}'

            b = sections[key]['buckets'].setdefault(
                q_hash, {'total': 0, 'correct': 0, 'answers': [], 'q_def': q_def})
            b['total'] += 1
            if isinstance(answer, dict) and answer.get('correct'):
                b['correct'] += 1
            b['answers'].append(answer)

    for t in extra_topics:
        tasks_meta.setdefault(t['id'], {'name': t['name'], 'quiz_json': t['quiz_json']})
        sections.setdefault((t['id'], None), {'reihenfolge': 9999, 'is_topic_quiz': True,
                                               'current_quiz_json': t['quiz_json'], 'buckets': {}})
    for sub in extra_subs:
        tid = sub['task_id']
        tasks_meta.setdefault(tid, {'name': sub['task_name'], 'quiz_json': None})
        sections.setdefault((tid, sub['id']), {'reihenfolge': sub['reihenfolge'], 'is_topic_quiz': False,
                                                'current_quiz_json': sub['quiz_json'], 'buckets': {}})

    def build_questions(current_quiz_json, buckets):
        # Seed empty buckets for questions in current quiz that have no attempts yet
        try:
            current_defs = json.loads(current_quiz_json).get('questions', []) if current_quiz_json else []
        except (json.JSONDecodeError, TypeError):
            current_defs = []
        for q_def in current_defs:
            h = _question_hash(q_def)
            buckets.setdefault(h, {'total': 0, 'correct': 0, 'answers': [], 'q_def': q_def})

        questions = []
        for q_hash, b in buckets.items():
            q_def = b['q_def']
            q_type = (q_def or {}).get('type', 'multiple_choice')
            q = {
                'text': (q_def or {}).get('text', '(Frage nicht verfügbar)'),
                'type': q_type,
                'total': b['total'],
                'correct_count': 0,
            }
            if q_type == 'multiple_choice':
                opts_raw = (q_def or {}).get('options', [])
                opt_texts = [o if isinstance(o, str) else o.get('text', '') for o in opts_raw]
                correct_set = set((q_def or {}).get('correct', []))
                counts = [0] * len(opt_texts)
                correct_n = 0
                for ans in b['answers']:
                    if not isinstance(ans, list):
                        continue
                    if set(ans) == correct_set:
                        correct_n += 1
                    for i in ans:
                        if 0 <= i < len(counts):
                            counts[i] += 1
                q['correct_count'] = correct_n
                q['options'] = [{'text': opt_texts[i], 'count': counts[i], 'is_correct': i in correct_set}
                                 for i in range(len(opt_texts))]
            else:
                q['correct_count'] = b['correct']
                freq = {}
                for ans in b['answers']:
                    text = (ans.get('text', '') if isinstance(ans, dict) else '').strip() or '(leer)'
                    freq[text] = freq.get(text, 0) + 1
                if for_export:
                    q['answers'] = [{'text': t, 'count': c}
                                     for t, c in sorted(freq.items(), key=lambda x: -x[1])]
                else:
                    q['answer_dist'] = sorted(freq.items(), key=lambda x: -x[1])[:10]
            questions.append(q)
        # Sort by question text for stable ordering (index no longer meaningful)
        return sorted(questions, key=lambda q: q['text'])

    by_task = {}
    for (tid, sid), sec in sections.items():
        qs = build_questions(sec['current_quiz_json'], sec['buckets'])
        if not qs:
            continue
        by_task.setdefault(tid, []).append({
            'position': sec['reihenfolge'],
            'is_topic_quiz': sec['is_topic_quiz'],
            'questions': qs,
        })

    result = []
    for tid, secs in by_task.items():
        sorted_secs = sorted(secs, key=lambda s: s['position'])
        sub_idx = 0
        for sec in sorted_secs:
            if not sec['is_topic_quiz']:
                sub_idx += 1
                sec['subtask_position'] = sub_idx
            else:
                sec['subtask_position'] = None
        result.append({'task_id': tid, 'task_name': tasks_meta[tid]['name'], 'sections': sorted_secs})

    return sorted(result, key=lambda t: t['task_name'])


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
                INSERT INTO error_log (level, message, traceback, user_id, user_type, route, method, url, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (level, message, traceback, user_id, user_type, route, method, url, now_local()))
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
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at""",
            (key, str(value), now_local())
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

def check_llm_rate_limit(student_id, usage_tag='llm_grading'):
    """Check if student is within their hourly LLM call limit for the given
    usage_tag's pool. Each tag has its own counter and ceiling so unrelated
    usage can't exhaust another pool's budget -- see record_llm_usage.

    Returns True if calls are allowed, False if rate limit exceeded.
    """
    limit = (config.LLM_MAX_CHECKPOINT_CALLS_PER_STUDENT_PER_HOUR if usage_tag == 'checkpoint_quiz'
             else config.LLM_MAX_CALLS_PER_STUDENT_PER_HOUR)
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM llm_usage "
            "WHERE student_id = ? AND question_type = ? "
            "AND timestamp > ?",
            (student_id, usage_tag, local_cutoff(hours=1))
        ).fetchone()
        return row['cnt'] < limit


def get_artifact_checks_remaining(student_id):
    """Return how many artifact KI-Checks the student can still do this hour."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM llm_usage "
            "WHERE student_id = ? AND question_type = 'artifact_feedback' "
            "AND timestamp > ?",
            (student_id, local_cutoff(hours=1))
        ).fetchone()
        return max(0, config.LLM_MAX_ARTIFACT_CHECKS_PER_STUDENT_PER_HOUR - row['cnt'])


# --- Artifact feedback ---

def save_artifact_feedback(student_id, subtask_id, feedback_list, timezone='Europe/Berlin'):
    """Store one LLM checklist result. Each upload creates a new row (history preserved)."""
    timestamp_local = now_local('%Y-%m-%dT%H:%M:%S')
    with db_session() as conn:
        conn.execute(
            "INSERT INTO artifact_feedback (student_id, subtask_id, timestamp_local, timezone, feedback_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (student_id, subtask_id, timestamp_local, timezone, json.dumps(feedback_list))
        )


def get_artifact_feedback(student_id, subtask_id):
    """Return the most recent feedback row for a student+subtask, or None."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT id, timestamp_local, timezone, feedback_json FROM artifact_feedback "
            "WHERE student_id = ? AND subtask_id = ? ORDER BY id DESC LIMIT 1",
            (student_id, subtask_id)
        ).fetchone()
    if not row:
        return None
    return {
        'id': row[0],
        'timestamp_local': row[1],
        'timezone': row[2],
        'feedback': json.loads(row[3]),
    }


def get_all_artifact_feedback_for_student(student_id):
    """Return all artifact_feedback rows for a student, newest first, enriched with subtask name."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT af.id, af.timestamp_local, af.timezone, af.feedback_json, "
            "       s.beschreibung, af.subtask_id "
            "FROM artifact_feedback af "
            "JOIN subtask s ON s.id = af.subtask_id "
            "WHERE af.student_id = ? ORDER BY af.id DESC",
            (student_id,)
        ).fetchall()
    return [
        {
            'id': r[0],
            'timestamp_local': r[1],
            'timezone': r[2],
            'feedback': json.loads(r[3]),
            'subtask_beschreibung': r[4],
            'subtask_id': r[5],
        }
        for r in rows
    ]


def get_artifact_gate_attempts_for_student(student_id):
    """Return all gate attempts for a student, newest first, with subtask task name."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT a.id, a.timestamp_local, a.passed, a.details_json, "
            "       t.name as task_name, s.reihenfolge as subtask_pos "
            "FROM artifact_gate_attempt a "
            "JOIN subtask s ON s.id = a.subtask_id "
            "JOIN task t ON t.id = s.task_id "
            "WHERE a.student_id = ? ORDER BY a.id DESC",
            (student_id,)
        ).fetchall()
    return [
        {
            'id': r['id'],
            'timestamp_local': r['timestamp_local'],
            'passed': bool(r['passed']),
            'details': json.loads(r['details_json']),
            'task_name': r['task_name'],
            'subtask_pos': r['subtask_pos'],
        }
        for r in rows
    ]


# --- Student artifact file (latest upload per unit, overwritten on re-upload) ---
# Keyed by task (unit), not subtask -- see "gradual artifact building" pattern,
# docs/shared/mbi/content-design.md. One growing document per unit.

def save_student_artifact_file(student_id, task_id, subtask_id, original_filename, disk_filename, timezone='Europe/Berlin'):
    """Store/replace the latest uploaded file record for a student+task. subtask_id records which checkpoint triggered this upload."""
    uploaded_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    with db_session() as conn:
        conn.execute(
            "INSERT INTO student_artifact_file (student_id, task_id, last_subtask_id, original_filename, disk_filename, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(student_id, task_id) DO UPDATE SET "
            "last_subtask_id = excluded.last_subtask_id, "
            "original_filename = excluded.original_filename, "
            "disk_filename = excluded.disk_filename, "
            "uploaded_at = excluded.uploaded_at",
            (student_id, task_id, subtask_id, original_filename, disk_filename, uploaded_at)
        )


def get_student_artifact_file(student_id, task_id):
    """Return the stored file record for a student+task (unit), or None."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT original_filename, disk_filename, uploaded_at, last_subtask_id FROM student_artifact_file "
            "WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)
        ).fetchone()
    if not row:
        return None
    return {
        'original_filename': row['original_filename'],
        'disk_filename': row['disk_filename'],
        'uploaded_at': row['uploaded_at'],
        'last_subtask_id': row['last_subtask_id'],
    }


def get_all_student_artifact_files_for_student(student_id):
    """Return all stored artifact files for a student, newest first, with task/checkpoint context."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT saf.task_id, saf.original_filename, saf.uploaded_at, "
            "       t.name as task_name, s.reihenfolge as subtask_pos "
            "FROM student_artifact_file saf "
            "JOIN task t ON t.id = saf.task_id "
            "JOIN subtask s ON s.id = saf.last_subtask_id "
            "WHERE saf.student_id = ? ORDER BY saf.uploaded_at DESC",
            (student_id,)
        ).fetchall()
    return [
        {
            'task_id': r['task_id'],
            'original_filename': r['original_filename'],
            'uploaded_at': r['uploaded_at'],
            'task_name': r['task_name'],
            'subtask_pos': r['subtask_pos'],
        }
        for r in rows
    ]


def set_klasse_llm_feedback(klasse_id, enabled: bool):
    """Enable or disable LLM artifact feedback for a class."""
    with db_session() as conn:
        conn.execute(
            "UPDATE klasse SET llm_artifact_feedback_enabled = ? WHERE id = ?",
            (1 if enabled else 0, klasse_id)
        )


def set_klasse_artifact_gate_required(klasse_id, required: bool):
    """Set whether artifact gate blocks task completion (True) or is informational (False)."""
    with db_session() as conn:
        conn.execute(
            "UPDATE klasse SET artifact_gate_required = ? WHERE id = ?",
            (1 if required else 0, klasse_id)
        )


def set_klasse_show_completed_topics(klasse_id, show: bool):
    """Set whether the student dashboard lists this class's finished Themen."""
    with db_session() as conn:
        conn.execute(
            "UPDATE klasse SET show_completed_topics = ? WHERE id = ?",
            (1 if show else 0, klasse_id)
        )



def get_completed_student_tasks(student_id, klasse_id):
    """Finished Themen for one student in one class, newest first.

    The dashboard's own get_student_task returns the *active* topic only, which
    is why a student who advanced through the queue had no route back to
    anything they had finished. Ordered by student_task.id descending as a
    stand-in for completion time: student_task carries no completed_at column,
    and rows are created in the order topics get assigned.
    """
    with db_session() as conn:
        rows = conn.execute(f"""
            SELECT st.id, st.task_id, st.abgeschlossen, st.manuell_abgeschlossen,
                   t.name, t.fach, t.stufe,
                   {_IS_SEILBAHN_SQL}
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.student_id = ? AND st.klasse_id = ?
              AND st.abgeschlossen = 1 AND st.rolle != 'sidequest'
            ORDER BY st.id DESC
        """, (student_id, klasse_id)).fetchall()
        return [dict(r) for r in rows]


def get_reopened_checkpoint_topics(student_id):
    """Themen where a checkpoint was reset and the student has not retaken it.

    Counterpart to get_reopened_checkpoint_notice, which answers the same
    question for one checkpoint the caller already knows about. This one has to
    *find* them: the student has usually moved on and will never open the page
    that carries that notice.

    "Not retaken" is the NOT EXISTS clause -- once a live (non-superseded)
    attempt lands for the same checkpoint, the retake carries its own review
    banner and this entry is stale.

    Returns one row per checkpoint (the newest reset), keyed by module_id so the
    caller can match it against a Thema. Not class-scoped: checkpoint_attempt
    carries no klasse_id, so the caller filters by the topics of the class.
    """
    with db_session() as conn:
        rows = conn.execute("""
            SELECT ca.module_id, ca.checkpoint_id, ca.student_feedback,
                   MAX(ca.superseded_at) AS superseded_at
            FROM checkpoint_attempt ca
            WHERE ca.student_id = ?
              AND ca.superseded_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM checkpoint_attempt live
                  WHERE live.student_id = ca.student_id
                    AND live.checkpoint_id = ca.checkpoint_id
                    AND live.superseded_at IS NULL
              )
            GROUP BY ca.checkpoint_id
            ORDER BY superseded_at DESC
        """, (student_id,)).fetchall()
        return [dict(r) for r in rows]


def record_llm_usage(student_id, question_type, tokens_used=0):
    """Record an LLM API call for rate limiting and monitoring."""
    with db_session() as conn:
        conn.execute(
            "INSERT INTO llm_usage (student_id, question_type, tokens_used, timestamp) VALUES (?, ?, ?, ?)",
            (student_id, question_type, tokens_used, now_local())
        )


# ============ Grading Service (grading-with-llm Phase 2) ============
# State machine per grading-service-deployment.md §7:
#   imported -> under_review -> active -> (visible to student)
#                    |-> corrected -> active   (teacher overrode a score, still active)
#                    |-> discarded             (bad run, re-grade)
#                    |-> superseded            (another run made active instead)

GRADING_RESULT_STATUSES = {'imported', 'under_review', 'active', 'corrected', 'discarded', 'superseded'}


def get_task_grading_keyword(task_id):
    """The graded_artifact keyword to use as the grading-service rubric slug
    for this task -- the LATEST subtask (highest reihenfolge) carrying a
    graded_artifact wins, since MBI's growing-rubric pattern accumulates
    criteria toward a capstone (conventions.md 'Growing rubric pattern'; the
    keyword is shared across all subtasks in the chain, but the last one's
    criteria list is the authoritative superset). None if the task has no
    graded_artifact anywhere."""
    keyword = None
    for st in get_subtasks(task_id):  # already ordered by reihenfolge ascending
        if not st.get('graded_artifact_json'):
            continue
        try:
            ga = json.loads(st['graded_artifact_json'])
        except (json.JSONDecodeError, TypeError):
            continue
        if ga.get('keyword'):
            keyword = ga['keyword']
    return keyword


def list_tasks_with_graded_artifact():
    """Tasks with at least one graded_artifact-bearing subtask -- the unit
    picker on the grading-service upload page (sub-phase 2f)."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT t.* FROM task t JOIN subtask s ON s.task_id = t.id "
            "WHERE s.graded_artifact_json IS NOT NULL "
            "ORDER BY t.fach, t.stufe, t.number, t.name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_task_by_grading_keyword(rubric):
    """Reverse of get_task_grading_keyword: find the task whose
    graded_artifact keyword chain matches this rubric slug. Returns the task
    id, or None if zero or more than one task matches -- callers must not
    guess (used by import_grading_callback to auto-create a grading_run for
    a job Lernmanager never registered itself; task_id is NOT NULL on both
    grading_run and grading_result, so a wrong guess would misroute grades,
    not just fail loudly)."""
    matches = [
        t['id'] for t in list_tasks_with_graded_artifact()
        if get_task_grading_keyword(t['id']) == rubric
    ]
    return matches[0] if len(matches) == 1 else None


def create_grading_run(job_id, klasse_id, task_id, rubric, provider, model,
                        total_students=0, flagged_count=0, zero_score_count=0, graded_at=None):
    """Create a grading_run row for one imported batch. klasse_id may be None
    -- a single upload can span students from several classes, or none known
    yet (a scan-folders-originated run auto-created from a results callback,
    see import_grading_callback). Returns the new id."""
    imported_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO grading_run (job_id, klasse_id, task_id, rubric, provider, model, "
            "imported_at, graded_at, total_students, flagged_count, zero_score_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, klasse_id, task_id, rubric, provider, model, imported_at, graded_at,
             total_students, flagged_count, zero_score_count)
        )
        return cursor.lastrowid


def get_grading_run(run_id):
    """Return a grading_run row (dict) enriched with klasse/task names, or
    None. klasse_name is None for a classless run (multi-class upload, or a
    scan-folders run auto-created from a results callback) -- LEFT JOIN, not
    INNER, so such a run doesn't silently vanish from get_grading_run."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT gr.*, k.name as klasse_name, t.name as task_name "
            "FROM grading_run gr "
            "LEFT JOIN klasse k ON k.id = gr.klasse_id "
            "JOIN task t ON t.id = gr.task_id "
            "WHERE gr.id = ?",
            (run_id,)
        ).fetchone()
    return dict(row) if row else None


def list_grading_runs(klasse_id=None):
    """List grading_run rows, newest first. Optionally filtered by class
    (classless runs are excluded when filtering, included otherwise)."""
    with db_session() as conn:
        if klasse_id is not None:
            rows = conn.execute(
                "SELECT gr.*, k.name as klasse_name, t.name as task_name "
                "FROM grading_run gr LEFT JOIN klasse k ON k.id = gr.klasse_id JOIN task t ON t.id = gr.task_id "
                "WHERE gr.klasse_id = ? ORDER BY gr.id DESC",
                (klasse_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT gr.*, k.name as klasse_name, t.name as task_name "
                "FROM grading_run gr LEFT JOIN klasse k ON k.id = gr.klasse_id JOIN task t ON t.id = gr.task_id "
                "ORDER BY gr.id DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def mark_grading_run_media_purged(run_id):
    """Record that this run's media directory has been deleted (retention, spec §7)."""
    purged_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    with db_session() as conn:
        conn.execute("UPDATE grading_run SET media_purged_at = ? WHERE id = ?", (purged_at, run_id))


def is_grading_run_settled(run_id):
    """True once every result in the run has left the review pipeline
    (active/discarded/superseded) -- nothing left that still needs the
    source media to review. Drives the auto-purge trigger below."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM grading_result "
            "WHERE grading_run_id = ? AND status IN ('imported', 'under_review', 'corrected')",
            (run_id,)
        ).fetchone()
    return row['cnt'] == 0


def purge_grading_run_media(run_id):
    """
    Retention sweep for one run (spec §7: "once a run is imported and
    released, the grading service should purge the extracted files and
    results" -- plus Lernmanager's own local copy). Best-effort on both
    legs: a failed DELETE against an already-purged/offline grading service
    must not block deleting the local copy, and vice versa -- whichever
    succeeds, succeeds; mark_grading_run_media_purged() records that the
    sweep ran regardless, so it isn't retried forever against a service
    that's simply offline.
    """
    import shutil
    run = get_grading_run(run_id)
    if run is None:
        return

    local_dir = os.path.join(_grading_upload_dir(), str(run_id))
    if os.path.isdir(local_dir):
        shutil.rmtree(local_dir, ignore_errors=True)

    if config.GRADING_SERVICE_URL and run.get('job_id'):
        req = urllib.request.Request(
            f"{config.GRADING_SERVICE_URL}/jobs/{run['job_id']}",
            method='DELETE',
            headers={'Authorization': f"Bearer {config.GRADING_SERVICE_TOKEN}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15):
                pass
        except (urllib.error.URLError, OSError, TimeoutError):
            pass  # already gone, or service unreachable -- not fatal, see docstring

    mark_grading_run_media_purged(run_id)


def maybe_auto_purge_grading_run(run_id):
    """Call after any action that can settle a run (release/discard) --
    purges media immediately once nothing is left to review, rather than
    waiting for a separate sweep job (spec §7 calls a time-based sweep a
    'backstop', not the primary mechanism)."""
    run = get_grading_run(run_id)
    if run and not run.get('media_purged_at') and is_grading_run_settled(run_id):
        purge_grading_run_media(run_id)


def get_grading_run_by_job_id(job_id):
    """Look up the grading_run created at upload time (sub-phase 2f) so the
    /internal/grading/results callback can find where to attach results --
    the grading service itself has no notion of klasse/task."""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM grading_run WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def match_netzwerk_logins(logins):
    """Resolve a list of already-normalized netzwerk_id logins (the browser
    parses the scan-folders zip client-side and normalizes folder names the
    same way ConvertTo-NormalizedLogin does in grading-upload.psm1) against
    the *global* student roster -- not one class's, since a single upload can
    now span several classes. Returns only matches, as
    {login, names: [vorname, nachname], lernpfad}, one per input login found.
    Deliberately not "return the whole roster and let the browser filter" --
    keeps the admin-only upload page from carrying every enrolled student's
    real name on every page load, only the ones actually present in this zip
    (grading-service-deployment.md §5's manifest shape)."""
    if not logins:
        return []
    with db_session() as conn:
        placeholders = ','.join('?' * len(logins))
        rows = conn.execute(
            f"SELECT netzwerk_id, vorname, nachname, lernpfad FROM student "
            f"WHERE netzwerk_id IN ({placeholders})",
            logins
        ).fetchall()
    return [
        {'login': r['netzwerk_id'], 'names': [r['vorname'], r['nachname']],
         'lernpfad': r['lernpfad'] or ''}
        for r in rows
    ]


def get_student_by_netzwerk_id(netzwerk_id):
    """Resolve a scan-folders folder name to an enrolled student, or None if
    unmatched (grading_result.student_id stays NULL -- surfaced in the review
    UI as needing manual reconciliation, never silently dropped)."""
    with db_session() as conn:
        row = conn.execute("SELECT id FROM student WHERE netzwerk_id = ?", (netzwerk_id,)).fetchone()
    return row['id'] if row else None


def _grading_upload_dir():
    """Computed fresh each call (not a frozen constant) so tests can override
    config.UPLOAD_FOLDER -- same convention as app.py's _artifact_upload_dir()."""
    return os.path.join(config.UPLOAD_FOLDER, 'grading')


_SAFE_NETZWERK_ID = re.compile(r'^[a-z0-9._-]+$')


def _copy_grading_media(run_id, job_id, netzwerk_id, media_list):
    """
    Download each graded image from the grading service's GET
    /jobs/<job_id>/media/<student>/<file> (Bearer-authed, teacher-review-ui.md
    §6) into instance/uploads/grading/<run_id>/<netzwerk_id>/ and rewrite
    'file' to the local relative path. Must happen at import time, not
    lazily: the source job (and its media) gets purged from the grading host
    once reviewed (spec §7's retention rule) -- there is nothing to fetch
    from later.

    A single download failure (network hiccup, service already purged this
    job) drops that one media entry rather than failing the whole import --
    matches the fire-and-forget philosophy of the callback itself. The
    review UI's media_skipped[] messaging already covers "no image was
    found here"; a failed copy reads the same way to a teacher.

    netzwerk_id here is caller-controlled (it's `student_id` straight out of
    the callback payload, security-review 2026-08-16 finding #4) -- it must
    never reach os.path.join unvalidated, or a crafted/compromised payload
    can write outside instance/uploads/grading/ entirely.
    """
    if not media_list or not config.GRADING_SERVICE_URL:
        return []
    if not _SAFE_NETZWERK_ID.match(netzwerk_id or ''):
        return []
    dest_dir = os.path.join(_grading_upload_dir(), str(run_id), netzwerk_id)
    os.makedirs(dest_dir, exist_ok=True)

    copied = []
    for m in media_list:
        raw_filename = m.get('file')
        if not raw_filename:
            continue
        filename = os.path.basename(raw_filename)
        url = f"{config.GRADING_SERVICE_URL}/jobs/{job_id}/media/{netzwerk_id}/{filename}"
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {config.GRADING_SERVICE_TOKEN}',
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
        with open(os.path.join(dest_dir, filename), 'wb') as f:
            f.write(data)
        entry = dict(m)
        entry['file'] = f"{run_id}/{netzwerk_id}/{filename}"
        copied.append(entry)
    return copied


def import_grading_callback(job_id, provider, model, graded_at, students, rubric=None):
    """
    Import the grading service's POST /internal/grading/results payload
    (worker.fire_callback's shape) into grading_result rows under the
    grading_run that sub-phase 2f created at upload time. Idempotent per
    student: re-delivering the same job_id is a no-op for students who
    already have a grading_result in this run (callback delivery is
    fire-and-forget on the service side -- spec §4 -- so a retry is possible;
    UNIQUE(job_id) on grading_run also makes the auto-create below race-safe
    against a concurrent duplicate delivery).

    If no grading_run exists yet for job_id, this is a scan-folders-
    originated job that was never registered with Lernmanager at upload time
    -- auto-create one (klasse_id=NULL, task_id resolved from rubric via
    get_task_by_grading_keyword) rather than dropping the results. Only when
    exactly one task's graded_artifact keyword matches rubric: task_id is
    NOT NULL on both grading_run and grading_result, so guessing wrong would
    misroute grades, not just fail loudly. Zero or ambiguous matches raise
    ValueError instead of guessing -- see todo.md § Graded Artifacts for the
    manual "import by job ID" recovery path for that case.

    Returns the grading_run id, or raises ValueError if no grading_run
    matches job_id and none could be safely auto-created.
    """
    run = get_grading_run_by_job_id(job_id)
    if run is None:
        task_id = get_task_by_grading_keyword(rubric) if rubric else None
        if task_id is None:
            raise ValueError(
                f"no grading_run for job_id={job_id!r} and rubric={rubric!r} did not "
                f"resolve to exactly one task -- cannot auto-create without guessing"
            )
        try:
            run_id = create_grading_run(
                job_id=job_id, klasse_id=None, task_id=task_id, rubric=rubric,
                provider=provider or 'unknown', model=model,
            )
            run = get_grading_run(run_id)
        except sqlite3.IntegrityError:
            # Lost a race against a concurrent duplicate callback delivery --
            # the other one already created it under UNIQUE(job_id).
            run = get_grading_run_by_job_id(job_id)

    with db_session() as conn:
        already_imported = {
            r['netzwerk_id'] for r in conn.execute(
                "SELECT netzwerk_id FROM grading_result WHERE grading_run_id = ?", (run['id'],)
            ).fetchall()
        }

    flagged_count = 0
    zero_score_count = 0
    imported = 0
    for s in students:
        netzwerk_id = s.get('student_id')  # grading-with-llm's field name for this key, not Lernmanager's numeric id
        if netzwerk_id in already_imported:
            continue
        student_id = get_student_by_netzwerk_id(netzwerk_id)
        total_score = s.get('total_score')
        max_score = s.get('max_score')
        flagged = bool(s.get('flagged'))
        if flagged:
            flagged_count += 1
        if total_score == 0:
            zero_score_count += 1
        media = _copy_grading_media(run['id'], job_id, netzwerk_id, s.get('media') or [])
        create_grading_result(
            grading_run_id=run['id'], task_id=run['task_id'], student_id=student_id,
            netzwerk_id=netzwerk_id, criteria=s.get('criteria', []),
            llm_total_score=total_score, llm_max_score=max_score, flagged=flagged,
            confidence=s.get('confidence'), error=s.get('error'),
            document_file=s.get('document_file'), media=media,
            media_skipped=s.get('media_skipped'),
        )
        imported += 1

    with db_session() as conn:
        conn.execute(
            "UPDATE grading_run SET provider = ?, model = ?, graded_at = ?, "
            "total_students = total_students + ?, flagged_count = flagged_count + ?, "
            "zero_score_count = zero_score_count + ? WHERE id = ?",
            (provider, model, graded_at, imported, flagged_count, zero_score_count, run['id'])
        )
    return run['id']


def create_grading_result(grading_run_id, task_id, student_id, netzwerk_id, criteria,
                           llm_total_score=None, llm_max_score=None, flagged=False,
                           confidence=None, error=None, document_file=None,
                           media=None, media_skipped=None):
    """
    Create one grading_result row (status='imported'). `criteria` is the list
    of per-criterion dicts from students/*.json, reshaped into the review-UI
    contract (teacher-review-ui.md §5): each gets teacher_score=None,
    overridden=False, reviewed_at=None added, plus review_required/confirmed
    if the rubric criterion carries review_required (sub-phase 2d).
    """
    created_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    criteria_json = json.dumps([
        {
            'name': c.get('name'),
            'llm_score': c.get('score'),
            'max_score': c.get('max_score'),
            'feedback': c.get('feedback', ''),
            'teacher_score': c.get('score'),
            'overridden': False,
            'reviewed_at': None,
            'review_required': bool(c.get('review_required')),
            'confirmed': not bool(c.get('review_required')),
        }
        for c in criteria
    ])
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO grading_result (grading_run_id, task_id, student_id, netzwerk_id, status, "
            "llm_total_score, llm_max_score, flagged, confidence, error, criteria_json, document_file, "
            "media_json, media_skipped_json, created_at) "
            "VALUES (?, ?, ?, ?, 'imported', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (grading_run_id, task_id, student_id, netzwerk_id, llm_total_score, llm_max_score,
             1 if flagged else 0, confidence, error, criteria_json, document_file,
             json.dumps(media or []), json.dumps(media_skipped or []), created_at)
        )
        return cursor.lastrowid


def _row_to_grading_result(row):
    d = dict(row)
    d['criteria'] = json.loads(d['criteria_json'])
    d['media'] = json.loads(d.pop('media_json') or '[]')
    d['media_skipped'] = json.loads(d.pop('media_skipped_json') or '[]')
    del d['criteria_json']
    d['flagged'] = bool(d['flagged'])
    return d


def get_grading_result(result_id):
    """Return one grading_result (dict, criteria/media parsed, student name joined), or None."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT gres.*, s.nachname, s.vorname "
            "FROM grading_result gres LEFT JOIN student s ON s.id = gres.student_id "
            "WHERE gres.id = ?",
            (result_id,)
        ).fetchone()
    return _row_to_grading_result(row) if row else None


def list_grading_results(grading_run_id):
    """List all grading_result rows for a run, joined with student name where resolved."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT gres.*, s.nachname, s.vorname "
            "FROM grading_result gres LEFT JOIN student s ON s.id = gres.student_id "
            "WHERE gres.grading_run_id = ? ORDER BY s.nachname, s.vorname, gres.netzwerk_id",
            (grading_run_id,)
        ).fetchall()
    return [_row_to_grading_result(r) for r in rows]


def get_active_grading_result(student_id, task_id):
    """The currently-active grading_result for (student, artifact), or None -- spec §7's
    'at most one active' rule. Used to detect supersede conflicts before release."""
    if student_id is None:
        return None
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM grading_result WHERE student_id = ? AND task_id = ? AND status = 'active'",
            (student_id, task_id)
        ).fetchone()
    return _row_to_grading_result(row) if row else None


def save_grading_result_review(result_id, criteria):
    """
    Page B 'Speichern' (teacher-review-ui.md §4): persist per-criterion
    teacher_score only where it differs from llm_score, mark overridden,
    stamp reviewed_at. Does NOT release -- status only advances to
    'under_review' if it was still 'imported'. Recomputes teacher_total_score.
    """
    reviewed_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    saved = []
    total = 0
    for c in criteria:
        teacher_score = c.get('teacher_score', c.get('llm_score'))
        overridden = teacher_score != c.get('llm_score')
        entry = dict(c)
        entry['teacher_score'] = teacher_score
        entry['overridden'] = overridden
        entry['reviewed_at'] = reviewed_at
        if 'review_required' in entry and entry['review_required'] and c.get('confirmed'):
            entry['confirmed'] = True
        saved.append(entry)
        if teacher_score is not None:
            total += teacher_score

    with db_session() as conn:
        conn.execute(
            "UPDATE grading_result SET criteria_json = ?, teacher_total_score = ?, reviewed_at = ?, "
            "status = CASE WHEN status = 'imported' THEN 'under_review' ELSE status END "
            "WHERE id = ?",
            (json.dumps(saved), total, reviewed_at, result_id)
        )


def release_grading_result(result_id, admin_id):
    """
    Page A/B release action (spec §7). Transitions this result to 'active'.
    If another result already holds 'active' for the same (student, task),
    that is a supersede: the caller must have already resolved it (picked a
    winner) -- this function does not choose for them. Raises ValueError if
    an unresolved conflict exists, so a route can't silently double-release.
    """
    released_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    with db_session() as conn:
        row = conn.execute("SELECT * FROM grading_result WHERE id = ?", (result_id,)).fetchone()
        if row is None:
            raise ValueError(f"grading_result {result_id} not found")
        if row['student_id'] is None:
            raise ValueError("cannot release a result with no matched student_id")

        criteria = json.loads(row['criteria_json'])
        unconfirmed = [c['name'] for c in criteria if c.get('review_required') and not c.get('confirmed')]
        if unconfirmed:
            raise ValueError(
                f"cannot release: always-review criteria not yet confirmed: {', '.join(unconfirmed)} "
                f"(teacher-review-ui.md §4)"
            )

        conflict = conn.execute(
            "SELECT id FROM grading_result WHERE student_id = ? AND task_id = ? "
            "AND status = 'active' AND id != ?",
            (row['student_id'], row['task_id'], result_id)
        ).fetchone()
        if conflict:
            raise ValueError(
                f"grading_result {conflict['id']} is already active for this student+task -- "
                f"resolve the supersede first (mark it superseded, pointing to {result_id})"
            )

        conn.execute(
            "UPDATE grading_result SET status = 'active', released_at = ?, released_by = ? WHERE id = ?",
            (released_at, admin_id, result_id)
        )


def supersede_grading_result(losing_result_id, winning_result_id):
    """Resolve a supersede conflict: mark the losing result 'superseded',
    pointing at the winner. Caller then calls release_grading_result on the winner."""
    with db_session() as conn:
        conn.execute(
            "UPDATE grading_result SET status = 'superseded', superseded_by_id = ? WHERE id = ?",
            (winning_result_id, losing_result_id)
        )


def discard_grading_result(result_id):
    """Mark a single result 'discarded' (bad run, re-grade)."""
    with db_session() as conn:
        conn.execute("UPDATE grading_result SET status = 'discarded' WHERE id = ?", (result_id,))


def discard_grading_run(run_id):
    """Bulk-discard every non-active result in a run (Page A 'discard whole run').
    Active results are left alone -- discarding a batch shouldn't retract
    feedback students can already see; discard those individually if truly needed."""
    with db_session() as conn:
        conn.execute(
            "UPDATE grading_result SET status = 'discarded' "
            "WHERE grading_run_id = ? AND status NOT IN ('active', 'superseded')",
            (run_id,)
        )


def is_non_submitter_result(result):
    """True for the sync path's zero-score placeholder row for an empty
    folder (processor.py's 'No document files found' case) -- these have no
    media to review, so teacher-review-ui.md §4 routes them through a
    one-click Page A confirm instead of the per-student Page B queue."""
    return result.get('document_file') is None and bool(result.get('error'))


def _review_queue_sort_key(result):
    """Flagged-first ordering for Page B (teacher-review-ui.md §4): (1) error
    rows on a real submission, (2) unconfirmed always-review criteria or any
    zero-score criterion, (3) alphabetical. Recomputed per page load rather
    than frozen at queue start (spec's stated ideal) -- see task_plan.md's
    2g/2h known-gaps note for why that's an acceptable MVP simplification
    here: the only input that changes mid-review is 'confirmed', and a
    result leaving bucket 2 because a teacher just confirmed it is a mild
    reshuffle, not the "queue points at a gone/superseded row" hazard the
    freeze was really guarding against (R3)."""
    is_real_error = bool(result.get('error')) and not is_non_submitter_result(result)
    needs_attention = any(
        (c.get('review_required') and not c.get('confirmed')) or c.get('llm_score') == 0
        for c in result['criteria']
    )
    bucket = 0 if is_real_error else (1 if needs_attention else 2)
    name = f"{result.get('nachname') or ''}, {result.get('vorname') or ''}"
    return (bucket, name)


def get_grading_run_review_queue(run_id):
    """Ordered list of grading_results for Page B's queue -- excludes
    non-submitters (handled on Page A) and anything already active/discarded/
    superseded (nothing left to review)."""
    reviewable = [
        r for r in list_grading_results(run_id)
        if not is_non_submitter_result(r) and r['status'] in ('imported', 'under_review', 'corrected')
    ]
    return sorted(reviewable, key=_review_queue_sort_key)


def get_next_in_review_queue(run_id, current_result_id):
    """The next result after current_result_id in the live queue order, or
    None at the end (Page B redirects back to Page A there)."""
    queue = get_grading_run_review_queue(run_id)
    ids = [r['id'] for r in queue]
    if current_result_id not in ids:
        return queue[0] if queue else None
    idx = ids.index(current_result_id)
    return queue[idx + 1] if idx + 1 < len(queue) else None


def get_grading_run_override_rate(run_id):
    """Count of overridden:true criteria / total reviewed criteria across the
    run (teacher-review-ui.md §5) -- the calibration signal the local-grading
    trust gate (todo.md) is waiting on. None if nothing has been reviewed yet."""
    total = 0
    overridden = 0
    for r in list_grading_results(run_id):
        for c in r['criteria']:
            if c.get('reviewed_at'):
                total += 1
                if c.get('overridden'):
                    overridden += 1
    if total == 0:
        return None
    return overridden / total


# ============ Warmup / Spaced Repetition ============

def _quiz_json_to_pool_entries(task_id, subtask_id, quiz_json, topic_name, completed_at=None,
                               student_path=None, fach=None):
    """Parse one quiz_json blob into warmup pool entries, filtering out
    question types too slow for a quick warm-up (short_answer, long_answer)
    and questions tagged for a path above the student's own.

    ordering and matching stay in: both grade deterministically in
    quiz_grading.py, so neither costs an LLM call or a noticeable wait."""
    try:
        quiz = json.loads(quiz_json)
    except (json.JSONDecodeError, TypeError):
        return []

    entries = []
    for i, q in enumerate(quiz.get('questions', [])):
        if q.get('type') in ('short_answer', 'long_answer'):
            continue
        if not is_question_visible_for_path(q, student_path):
            continue
        entry = {
            'task_id': task_id,
            'subtask_id': subtask_id,
            'question_index': i,
            'question_hash': _question_hash(q),
            'question': q,
            'topic_name': topic_name,
            # Carried per entry, not per session: a practice run mixes Themen from
            # every class the student is in, so the Chemie character bar has to
            # appear and disappear question by question.
            'fach': fach,
        }
        if completed_at is not None:
            entry['completed_at'] = completed_at
        entries.append(entry)
    return entries


def get_warmup_question_pool(student_id):
    """Build the warm-up/practice question pool for one student.

    A question only enters the pool if the student actually sat the quiz it
    came from -- a quiz_attempt row must exist. Topic completion alone is not
    enough: a topic marked complete by hand (admin override) has no attempts
    behind it, and warming up on questions the student never opened is not
    repetition, it is a first encounter.

    Class-wide practice unlocks (class_practice_unlock) are the deliberate
    exception -- the teacher opted the whole class in, so no attempt is
    required there. Those get filtered by learning path and fork branch
    instead, since there is no attempt to prove the student ever did the task.

    Returns list of dicts: [{task_id, subtask_id, question_index, question, topic_name}, ...]
    Filters out short_answer/long_answer questions (too slow for quick warm-up)
    and Einführung subtasks (is_intro -- questions don't work out of context).
    """
    pool = []
    with db_session() as conn:
        row = conn.execute(
            'SELECT lernpfad FROM student WHERE id = ?', (student_id,)).fetchone()
        student_path = row['lernpfad'] if row else None
        fork_choices = {
            r['fork_group']: r['fork_branch'] for r in conn.execute(
                'SELECT fork_group, fork_branch FROM student_fork_choice WHERE student_id = ?',
                (student_id,))
        }

        # 1. Topic quizzes the student has actually attempted
        attempted_topics = conn.execute('''
            SELECT DISTINCT t.id as task_id, t.name, t.quiz_json, t.fach
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            JOIN quiz_attempt qa ON qa.student_task_id = st.id AND qa.subtask_id IS NULL
            WHERE st.student_id = ?
              AND t.quiz_json IS NOT NULL AND t.quiz_json != ''
        ''', (student_id,)).fetchall()

        for topic in attempted_topics:
            pool.extend(_quiz_json_to_pool_entries(
                topic['task_id'], None, topic['quiz_json'], topic['name'],
                student_path=student_path, fach=topic['fach']))

        # 2. Aufgabe quizzes the student has actually attempted
        attempted_subtasks = conn.execute('''
            SELECT DISTINCT sub.id as subtask_id, sub.task_id, sub.quiz_json,
                   t.name as topic_name, t.fach, ss.completed_at
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            JOIN subtask sub ON sub.task_id = t.id
            JOIN quiz_attempt qa ON qa.student_task_id = st.id AND qa.subtask_id = sub.id
            LEFT JOIN student_subtask ss ON ss.student_task_id = st.id AND ss.subtask_id = sub.id
            WHERE st.student_id = ?
              AND sub.quiz_json IS NOT NULL AND sub.quiz_json != ''
              AND COALESCE(sub.is_intro, 0) = 0
        ''', (student_id,)).fetchall()

        for sub in attempted_subtasks:
            pool.extend(_quiz_json_to_pool_entries(
                sub['task_id'], sub['subtask_id'], sub['quiz_json'], sub['topic_name'],
                completed_at=sub['completed_at'], student_path=student_path,
                fach=sub['fach']))

        # 3. Class-unlocked topics → questions for students in that class,
        #    regardless of whether the topic was ever assigned to the student.
        seen_task_ids = {(e['task_id'], e['subtask_id']) for e in pool}

        unlocked_topics = conn.execute('''
            SELECT DISTINCT t.id as task_id, t.name, t.quiz_json, t.fach
            FROM student_klasse sk
            JOIN class_practice_unlock cpu ON cpu.klasse_id = sk.klasse_id
            JOIN task t ON t.id = cpu.task_id
            WHERE sk.student_id = ?
              AND t.quiz_json IS NOT NULL AND t.quiz_json != ''
        ''', (student_id,)).fetchall()

        for topic in unlocked_topics:
            if (topic['task_id'], None) in seen_task_ids:
                continue
            pool.extend(_quiz_json_to_pool_entries(
                topic['task_id'], None, topic['quiz_json'], topic['name'],
                student_path=student_path, fach=topic['fach']))

        unlocked_subtasks = conn.execute('''
            SELECT DISTINCT sub.id as subtask_id, sub.task_id, sub.quiz_json,
                   sub.path, sub.path_model, sub.fork_group, sub.fork_branch,
                   t.name as topic_name, t.fach
            FROM student_klasse sk
            JOIN class_practice_unlock cpu ON cpu.klasse_id = sk.klasse_id
            JOIN task t ON t.id = cpu.task_id
            JOIN subtask sub ON sub.task_id = t.id
            WHERE sk.student_id = ?
              AND sub.quiz_json IS NOT NULL AND sub.quiz_json != ''
              AND COALESCE(sub.is_intro, 0) = 0
        ''', (student_id,)).fetchall()

        for sub in unlocked_subtasks:
            if (sub['task_id'], sub['subtask_id']) in seen_task_ids:
                continue
            sub = dict(sub)
            # No attempt proves the student did this one, so fall back to what
            # was asked of them: their path, and the fork branch they picked.
            if not is_subtask_required_for_path(sub, student_path):
                continue
            if sub['fork_group'] and fork_choices.get(sub['fork_group']) != sub['fork_branch']:
                continue
            pool.extend(_quiz_json_to_pool_entries(
                sub['task_id'], sub['subtask_id'], sub['quiz_json'], sub['topic_name'],
                student_path=student_path, fach=sub['fach']))

    return pool


# Leitner box intervals (days to wait before re-showing), indexed by streak (capped at 4)
LEITNER_INTERVALS = [0, 1, 3, 7, 14]


def select_warmup_questions(student_id, pool, difficulty='easy', count=2, respect_intervals=True):
    """Select questions from pool based on difficulty and history.

    Difficulty (per-student, not per-question):
      - 'easy': questions with streak >= 2 OR never seen
      - 'hard': questions with streak < 2 AND seen before
      - 'mixed': no filter (for practice mode)

    respect_intervals: if True, only "due" questions are eligible (Leitner intervals).
      Set False for practice mode where students actively seek extra review.
    """
    if not pool:
        return []

    with db_session() as conn:
        history_rows = conn.execute(
            'SELECT task_id, subtask_id, question_hash, times_shown, times_correct, last_shown, streak '
            'FROM warmup_history WHERE student_id = ?',
            (student_id,)
        ).fetchall()

    history = {}
    for h in history_rows:
        key = (h['task_id'], h['subtask_id'], h['question_hash'])
        history[key] = dict(h)

    today = datetime.now().date()

    bucket = []
    for q in pool:
        key = (q['task_id'], q['subtask_id'], q['question_hash'])
        h = history.get(key)

        # Leitner interval gate: skip questions not yet due
        if respect_intervals and h is not None:
            streak = h['streak']
            interval = LEITNER_INTERVALS[min(streak, len(LEITNER_INTERVALS) - 1)]
            if h['last_shown']:
                last = datetime.strptime(h['last_shown'], '%Y-%m-%d').date()
                days_since = (today - last).days
            else:
                days_since = 999
            if days_since < interval:
                continue  # not due yet

        if difficulty == 'mixed':
            bucket.append(q)
        elif difficulty == 'easy':
            if h is None or h['streak'] >= 2:
                bucket.append(q)
        elif difficulty == 'hard':
            if h is not None and h['streak'] < 2:
                bucket.append(q)

    if not bucket:
        return []

    return _prioritize_questions(bucket, history, today.strftime('%Y-%m-%d'), count)


def _prioritize_questions(bucket, history, today, count):
    """Prioritize questions within a difficulty bucket.

    Tier 1: Previously incorrect (need reinforcement most)
    Tier 2: Recently completed task (within 7 days) AND never seen in warmup
            → surface new learning while still fresh
    Tier 3: Everything else due

    Returns up to `count` questions.
    """
    import random

    recent_cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    tier1 = []  # previously incorrect
    tier2 = []  # new learning, not yet seen in warmup
    tier3 = []  # everything else

    for q in bucket:
        key = (q['task_id'], q['subtask_id'], q['question_hash'])
        h = history.get(key)
        completed_at = q.get('completed_at')

        if h is not None and h['times_correct'] < h['times_shown']:
            tier1.append(q)
        elif h is None and completed_at and completed_at >= recent_cutoff:
            tier2.append(q)
        else:
            tier3.append(q)

    random.shuffle(tier1)
    random.shuffle(tier2)
    random.shuffle(tier3)

    selected = []
    for tier in [tier1, tier2, tier3]:
        for q in tier:
            if len(selected) >= count:
                break
            selected.append(q)
        if len(selected) >= count:
            break

    return selected


def record_warmup_answer(student_id, task_id, subtask_id, question_hash, correct):
    """Upsert warmup_history: update streak, times_shown/correct, last_shown."""
    with db_session() as conn:
        existing = conn.execute(
            'SELECT id, streak FROM warmup_history '
            'WHERE student_id = ? AND task_id IS ? AND subtask_id IS ? AND question_hash = ?',
            (student_id, task_id, subtask_id, question_hash)
        ).fetchone()

        today = datetime.now().strftime('%Y-%m-%d')

        if existing:
            new_streak = (existing['streak'] + 1) if correct else 0
            conn.execute(
                'UPDATE warmup_history SET times_shown = times_shown + 1, '
                'times_correct = times_correct + ?, last_shown = ?, streak = ? '
                'WHERE id = ?',
                (1 if correct else 0, today, new_streak, existing['id'])
            )
        else:
            conn.execute(
                'INSERT INTO warmup_history '
                '(student_id, task_id, subtask_id, question_hash, times_shown, times_correct, last_shown, streak) '
                'VALUES (?, ?, ?, ?, 1, ?, ?, ?)',
                (student_id, task_id, subtask_id, question_hash,
                 1 if correct else 0, today, 1 if correct else 0)
            )


def save_warmup_session(student_id, questions_shown, questions_correct, skipped=False, session_type='warmup'):
    """Log a warmup/practice session. session_type: 'warmup' or 'practice'."""
    with db_session() as conn:
        conn.execute(
            'INSERT INTO warmup_session (student_id, questions_shown, questions_correct, skipped, session_type, timestamp) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (student_id, questions_shown, questions_correct, 1 if skipped else 0, session_type,
             now_local())
        )


def count_practice_sessions_today(student_id):
    """Count student-initiated practice sessions completed today."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM warmup_session "
            "WHERE student_id = ? AND session_type = 'practice' AND DATE(timestamp) = DATE('now')",
            (student_id,)
        ).fetchone()
        return row[0] if row else 0


def has_done_warmup_today(student_id):
    """Check if student already completed a warmup session today."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT 1 FROM warmup_session WHERE student_id = ? AND DATE(timestamp) = DATE('now') LIMIT 1",
            (student_id,)
        ).fetchone()
        return row is not None
