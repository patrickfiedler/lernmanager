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

### Dependencies
```bash
pip install -r requirements.txt
```

## Architecture

### Core Files
- `app.py` - Flask application with all routes. Two user types: admin (teachers) and student. Uses session-based auth with `@admin_required` and `@student_required` decorators.
- `models.py` - SQLite database layer with raw SQL queries. Uses `db_session()` context manager for transactions.
- `config.py` - Configuration constants (database path, upload settings, subjects/levels, LLM grading settings).
- `utils.py` - Username/password generators for student accounts, `slugify()` for URL-friendly topic slugs.
- `llm_grading.py` - LLM-based grading for free-text quiz answers (`fill_blank`, `short_answer`). Supports Anthropic cloud and local Ollama. Rate-limited, with automatic fallback on errors.

### Database Schema (SQLite)
Key tables: `admin`, `klasse` (class), `student`, `student_klasse` (many-to-many), `task` (Thema/topic with optional topic-level quiz), `subtask` (Aufgabe/task with optional per-task quiz), `material` (links/files), `student_task` (per-class assignment, has `current_subtask_id`), `student_subtask` (per-task completion), `subtask_visibility` (per-student/class task visibility), `quiz_attempt` (quiz results), `unterricht` (lesson attendance/evaluation), `analytics_events` (activity logging), `llm_usage` (LLM rate limiting).

Each student has one active topic per class. Topics have tasks (subtasks) with optional quizzes (JSON in `quiz_json` column on both `task` and `subtask` tables).

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
- Quiz JSON format supports three question types:
  - Multiple choice (default): `{"text": "...", "options": ["..."], "correct": [0, 1]}`
  - Fill-in-blank: `{"type": "fill_blank", "text": "Die Hauptstadt ist ___.", "answers": ["Berlin", "berlin"]}`
  - Short answer (LLM-graded): `{"type": "short_answer", "text": "Erkläre...", "rubric": "Key concepts..."}`
- Quiz images (optional): `"image": "/path/to/img.png"` on questions, `{"text": "...", "image": "..."}` for options

### Content Formatting

**Markdown rendering** (`app.py`, `markdown_filter`): All text fields are rendered as Markdown with extensions `nl2br` (single `\n` = `<br>`), `fenced_code`, `tables`, `sane_lists`.

**Subtask descriptions** follow a structured format:
- `### Title` (h3 heading — the page uses h1 for the topic name)
- Emoji section markers: `🎯 Ziel:`, `📋 Aufgabe:`, `💡 Tipp:`, `✅ Fertig wenn:`
- Numbered lists for work steps, standard markdown `-` for sub-items

**Full format spec**: `docs/task_json_format.md` — also serves as a Claude prompt for generating new content.

### Learning Paths (Planned, not yet implemented)

Curriculum spec: `docs/2026-02-13_lernmanager_curriculum_spec.md`

Three cumulative difficulty paths per student: 🟢 Wanderweg (foundational) ⊂ 🔵 Bergweg (full curriculum) ⊂ ⭐ Gipfeltour (everything).

- Each subtask has a `path` field (`wanderweg`/`bergweg`/`gipfeltour`) = lowest path that includes it
- `path_model`: `skip` (lower paths skip task entirely) or `depth` (all paths do it, different grading expectations)
- **All tasks are visible** to all students — non-required tasks are styled as optional, NOT hidden
- **Learning paths take precedence over `subtask_visibility`**: path is the default; visibility settings are admin overrides for special cases only. Switching paths overrides visibility.
- Progress completion depends on student's chosen path
- Graded artifacts: some tasks produce graded files (`graded_artifact` field with `keyword`, `format`, `rubric`)
- Spaced repetition: weekly quiz from completed question pools (not yet designed)

**DB changes needed** (not yet migrated): `path` + `path_model` on `subtask`, `lernpfad` on `student`, `graded_artifact_json` on `subtask`. See `todo.md` for full checklist.

### Student URL Structure (Slug-Based)

Student-facing routes use human-readable slugs instead of numeric DB IDs. Slugs are computed on-the-fly via `slugify(task['name'])` — not stored in the DB.

| URL pattern | Route function | Purpose |
|-------------|---------------|---------|
| `/schueler` | `student_dashboard` | Dashboard |
| `/schueler/thema/<slug>` | `student_klasse` | Topic view (was `/schueler/klasse/<id>`) |
| `/schueler/thema/<slug>?aufgabe=<pos>` | (same) | Specific task by 1-based position (was `?subtask_id=<id>`) |
| `/schueler/thema/<slug>/aufgabe/<pos>` | `student_toggle_subtask` | POST: toggle task completion |
| `/schueler/thema/<slug>/quiz` | `student_quiz` | Topic-level quiz |
| `/schueler/thema/<slug>/aufgabe-<pos>/quiz` | `student_quiz_subtask` | Per-task quiz |
| `/schueler/thema/<slug>/quiz-ergebnis` | `student_quiz_result` | View topic quiz result |
| `/schueler/thema/<slug>/aufgabe-<pos>/quiz-ergebnis` | `student_quiz_result_subtask` | View task quiz result |

**Key helpers in `app.py`:**
- `_resolve_student_topic(student_id, slug)` → resolves slug to `(task, klasse)` by iterating student's classes
- `_resolve_subtask_by_position(subtasks, position)` → returns subtask at 1-based position
- `_handle_quiz(...)` → shared GET/POST quiz logic for both topic and subtask quizzes
- `_build_display_quiz(quiz)` → transforms quiz JSON (`text`/`options`) to template format (`question`/`answers`)

**Jinja2 filter:** `{{ task.name|slugify }}` available in all templates for generating slug URLs.

**When adding new student routes:** Use slug/position pattern, resolve to numeric IDs internally for DB operations. Never expose `student_task.id`, `subtask.id`, or `klasse.id` in student-facing URLs.

### Progress Dots and Quiz Dots

The task page shows progress dots: `[task] [?] [task] [task] [?] [topic-quiz?]`

- **Task dots** (`.dot.dot-subtask`): gray (incomplete), green (completed), blue ring (current)
- **Subtask quiz dots** (`.dot.dot-subtask-quiz`): smaller (1.25rem), gray (locked — task not done), amber `.available` (task done, quiz not passed), green `.completed` (passed)
- **Topic quiz dot** (`.dot.dot-quiz`): amber (available), green (passed)
- Progress text ("X von Y Aufgaben erledigt") counts only `.dot-subtask` elements, not quiz dots

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
