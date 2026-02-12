# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lernmanager is a German-language learning progress tracker for schools. It allows teachers (admins) to manage classes, students, and learning topics (Themen), while students can track their progress on assigned tasks (Aufgaben), complete them with quizzes, and take topic-level quizzes.

**Repository**: https://github.com/patrickfiedler/lernmanager

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
Key tables: `admin`, `klasse` (class), `student`, `task` (Thema/topic with optional topic-level quiz), `subtask` (Aufgabe/task with optional per-task quiz), `material` (links/files), `student_task` (per-class assignment), `quiz_attempt` (quiz results), `unterricht` (lesson attendance/evaluation).

Student-class is many-to-many. Each student has one active topic per class. Topics have tasks (subtasks) with optional quizzes (JSON in `quiz_json` column on both `task` and `subtask` tables).

### Template Structure
- `templates/admin/` - Teacher interface (class/student/task management, lesson tracking)
- `templates/student/` - Student interface (task progress, quiz taking, self-evaluation)

### Data Flow
1. Admin creates classes and topics (Themen) with tasks (Aufgaben)/materials/quizzes
2. Admin adds students to classes (batch input: "Nachname, Vorname" per line)
3. Admin assigns topics to individual students or entire classes
4. Students complete tasks: finish task → take per-task quiz (if any, 70% to pass) → next task
5. After all tasks done: take topic-level quiz (if any, 70% to pass)
6. Topic auto-completes when all visible tasks done + all quizzes passed (or admin manual override)

## Deployment

### Initial Server Setup
- Run `deploy/setup.sh` on the server (once per server)
- Automated one-command setup: `curl -sSL https://raw.githubusercontent.com/patrickfiedler/lernmanager/main/deploy/setup.sh | sudo bash`
- Auto-generates SECRET_KEY and stores in systemd service
- Creates lernmanager user, clones repo, sets up venv, starts service

### Updates
- Run `deploy/update.sh` on server after pushing to GitHub
- Usage: `ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'`
- Auto-detects changes in requirements.txt and systemd service
- Preserves secrets across updates
- Automatically rolls back if service fails to start

### Git Workflow
- Work directly on **main** branch
- Commit and push changes to GitHub
- SSH to server and run update.sh
- The update script will pull latest code and restart service

## Conventions

### Terminology (IMPORTANT)
The UI was renamed but the database tables keep the old names. Always use the correct mapping:

| UI (German) | UI (English) | DB table | DB parent |
|-------------|-------------|----------|-----------|
| Thema | Topic | `task` | — |
| Aufgabe | Task | `subtask` | `task_id` |
| Schüler-Thema | Student Topic | `student_task` | — |

In commit messages and docs, use the **UI terminology** (Thema/topic, Aufgabe/task). In code, the DB names (`task`, `subtask`) are used.

- German terminology in UI: Klasse (class), Schüler (student), Thema (topic), Aufgabe (task)
- Student usernames are auto-generated (adjective+animal, e.g., "happypanda")
- Student passwords follow cvcvcvnn pattern (e.g., "bacado42")
- Quiz JSON format: `{"questions": [{"text": "...", "options": ["..."], "correct": [0, 1]}]}`
- Quiz images (optional): `"image": "/path/to/img.png"` on questions, `{"text": "...", "image": "..."}` for options

## Common Issues and Solutions

### Template Block Structure
Jinja2 templates use `{% block scripts %}` and `{% block content %}` inheritance. The base template wraps `scripts` block with `<script>` tags. Never add additional `<script>` tags inside the block - this creates nested tags and breaks JavaScript execution.

### Unsaved Changes Detection
When tracking form state with `beforeunload` event listener, always update `initialState` after successful save and before reload to prevent false unsaved changes warnings.

### Subtask Visibility and Task Assignment
When editing subtasks via `models.update_subtasks()`, be aware of cascading effects:
- Deleting subtasks orphans `student_task.current_subtask_id` references
- Deleting subtasks orphans `subtask_visibility` records (controls which subtasks students see)
- **Solution**: Preserve visibility by subtask position/order, not by ID
- Map old subtask position 1 → new subtask position 1 (even with different IDs)
- Update `student_task.current_subtask_id` to point to first new subtask

**See**: `docs/archive/2026-01-27_ux_tier1_implementation/task_visibility_bug_plan.md`

### Easy Reading Mode Scope
When adding user-specific features that affect template rendering:
- Check `session.student_id` or `session.admin_id` to verify user type
- Don't rely solely on presence of user object (admins may view student pages)
- Example: `{% if student and student.easy_reading_mode and session.student_id %}`

**See**: `docs/archive/2026-01-27_ux_tier1_implementation/easy_reading_mode_scope_fix.md`

### Template Context Requirements
When adding new features that use session/user data in base template:
- Ensure ALL routes pass required objects (e.g., `student` object)
- Routes that render templates: check what base.html needs
- Example: student_klasse, student_quiz routes needed `student=student` in render_template

### Database Migrations
For encrypted SQLCipher databases:
- Pass SQLCIPHER_KEY via environment variable
- Migrations must handle both encrypted and unencrypted databases
- Always run migrations BEFORE deploying code changes
- Test migrations locally before production

**See**: Migration scripts in project root (e.g., `migrate_add_time_estimates.py`)
