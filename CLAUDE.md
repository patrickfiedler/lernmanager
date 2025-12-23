# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lernfortschritt is a German-language learning progress tracker for schools. It allows teachers (admins) to manage classes, students, and learning tasks, while students can track their progress on assigned tasks, complete subtasks, and take quizzes.

## Commands

### Development
```bash
# Run development server (port 5000, debug mode)
python app.py

# Run production server with waitress (port 8080)
python run.py
```

### Docker
```bash
docker compose up --build
```

### Dependencies
```bash
pip install -r requirements.txt
```

## Architecture

### Core Files
- `app.py` - Flask application with all routes. Two user types: admin (teachers) and student. Uses session-based auth with `@admin_required` and `@student_required` decorators.
- `models.py` - SQLite database layer with raw SQL queries. Uses `db_session()` context manager for transactions.
- `config.py` - Configuration constants (database path, upload settings, subjects/levels).
- `utils.py` - Username/password generators for student accounts.

### Database Schema (SQLite)
Key tables: `admin`, `klasse` (class), `student`, `task` (learning task with optional quiz), `subtask`, `material` (links/files), `student_task` (per-class assignment), `unterricht` (lesson attendance/evaluation).

Student-class is many-to-many. Each student has one active task per class. Tasks can have subtasks and quizzes (JSON in `quiz_json` column).

### Template Structure
- `templates/admin/` - Teacher interface (class/student/task management, lesson tracking)
- `templates/student/` - Student interface (task progress, quiz taking, self-evaluation)

### Data Flow
1. Admin creates classes and tasks with subtasks/materials/quizzes
2. Admin adds students to classes (batch input: "Nachname, Vorname" per line)
3. Admin assigns tasks to individual students or entire classes
4. Students complete subtasks and take quizzes (80% to pass)
5. Task auto-completes when all subtasks done + quiz passed (or admin manual override)

## Conventions

- German terminology in code: Klasse (class), Schüler (student), Aufgabe (task), Teilaufgabe (subtask)
- Student usernames are auto-generated (adjective+animal, e.g., "happypanda")
- Student passwords follow cvcvcvnn pattern (e.g., "bacado42")
- Quiz JSON format: `{"questions": [{"text": "...", "options": ["..."], "correct": [0, 1]}]}`
