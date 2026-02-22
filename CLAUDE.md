# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lernmanager is a German-language learning progress tracker for schools. It allows teachers (admins) to manage classes, students, and learning topics (Themen), while students can track their progress on assigned tasks (Aufgaben), complete them with quizzes, and take topic-level quizzes.

**Repository**: https://github.com/patrickfiedler/lernmanager

### Shared Decisions
Cross-project decisions are symlinked at `docs/shared/` → `~/coding/shared-decisions/`. Each project maintains a subfolder with key decision documents. Read relevant files when making decisions that affect content format, pedagogical approach, or technical constraints shared across projects.

Current projects in shared-decisions:

**`lernmanager/`** (this project):
- `pedagogical.md` — teaching philosophy, key decisions, known tensions
- `technical.md` — architecture, DB/UI terminology mapping, key technical choices
- `conventions.md` — content format contract (Aufgabe descriptions, paths, quizzes, JSON import)

**`mbi/`** (MBI curriculum content — units, tasks, quizzes for Medienbildung & Informatik grades 5/6):
- `pedagogical.md` — content-side teaching decisions: fun-first sequencing, tight scaffolding for 10-12yr, spiral progression, accepted trade-offs
- `content-design.md` — gradual artifact building (📎 pattern), task/quiz design, differentiation models (skip vs. depth), 60-lesson budget constraint
- `conventions.md` — authoring conventions: unit workflow (design doc → JSON → import), file naming, UTF-8 encoding, language rules, student-facing text fields

**`grading-with-llm/`** (automated artifact grading via LLM micro-prompting):
- `pedagogical.md` — why automated grading (feedback timing > speed), objective criteria only, LLM as tool not authority, structural assignments first
- `technical.md` — Python CLI, Anthropic Batch API (Haiku 4.5, 98.3% accuracy), micro-prompting pattern, anonymization, CSV/Markdown/JSON output
- `conventions.md` — data contract: input filenames (`nachname.vorname.docx`), rubric format (YAML frontmatter), per-student JSON output, integration via `graded_artifact.keyword`

**Key integration points:**
- MBI generates curriculum content → imported into Lernmanager via `lernmanager/conventions.md` JSON format
- Grading system outputs per-student JSON → planned Lernmanager API consumes it via `graded_artifact.keyword` matching
- All use UI terminology (Topic/Thema, Aufgabe), not DB names (task, subtask)

See `docs/shared/README.md` for structure and how to add new projects.

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
Key tables: `admin`, `klasse` (class), `student`, `student_klasse` (many-to-many), `task` (Thema/topic with optional topic-level quiz), `subtask` (Aufgabe/task with optional per-task quiz), `material` (links/files), `student_task` (per-class assignment, has `current_subtask_id`), `student_subtask` (per-task completion), `subtask_visibility` (per-student/class task visibility), `quiz_attempt` (quiz results), `unterricht` (lesson attendance/evaluation), `analytics_events` (activity logging), `llm_usage` (LLM rate limiting), `topic_queue` (ordered topic sequence per class, optional).

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

### Learning Paths (Implemented)

Curriculum spec: `docs/2026-02-13_lernmanager_curriculum_spec.md`

Three cumulative difficulty paths per student: 🟢 Wanderweg (foundational) ⊂ 🔵 Bergweg (full curriculum) ⊂ ⭐ Gipfeltour (everything).

- Each subtask has a `path` field (`wanderweg`/`bergweg`/`gipfeltour`) = lowest path that includes it
- `path_model`: `skip` (lower paths skip task entirely) or `depth` (all paths do it, different grading expectations)
- **All tasks are visible** to all students — non-required tasks use diamond-shaped dots and "Zusatz" badge, NOT hidden
- **Path scope is global** (student-level `lernpfad` column). Per-topic path override is a future option.
- **Teacher assigns path** via admin student detail page (`POST /admin/schueler/<id>/lernpfad`). Students cannot change their own path.
- **Student UI shows "Pflicht/Zusatz" only** — no path names (Wanderweg/Bergweg/Gipfeltour) visible to students. Admin UI still shows path names.
- **Zusatz dots use diamond shape** (rotated square via `transform: rotate(45deg)`) — colorblind-accessible shape distinction instead of dimming.
- Progress completion only counts path-required subtasks
- `hidden` column on `subtask`: simple admin override to hide specific subtasks from ALL students
- Legacy fallback: students without a `lernpfad` value use old `subtask_visibility` query
- **Old visibility management UI removed** (4 routes, 421-line template deleted). `subtask_visibility` table kept in DB for legacy data.
- Admin subtask editor includes path/path_model dropdowns per subtask
- Graded artifacts: `graded_artifact_json` column on `subtask` (JSON with `keyword`, `format`, `rubric`). UI display not yet implemented.
- Spaced repetition: **Implemented** — see "Warmup / Spaced Repetition" section below
- **Prerequisites removed from UI/code** (2026-02-15): `task_voraussetzung` DB table kept for potential future use, but all model functions, admin UI, import/export handling removed. Topic queue (Phase 4) replaces progression logic via queue ordering per class.

### Topic Queue (Implemented)

Optional per-class ordered topic sequence. Admins define a progression order; students self-advance when they complete a topic.

- **Queue is optional**: classes without a queue work exactly as before (manual assignment only)
- Admin manages queue at `/admin/klasse/<id>/themen-reihenfolge` — up/down/remove/add UI, one save button
- `topic_queue` table: `klasse_id`, `task_id`, `position` (1-based, UNIQUE per class+task)
- Model functions: `get_topic_queue()`, `set_topic_queue()`, `get_next_queued_topic()`, `get_queue_position()`
- Student progression: `POST /schueler/naechstes-thema` with `task_id` + `klasse_id` in form body — validates class membership + queue membership, then calls `assign_task_to_student()`
- Dashboard shows "Nächstes Thema" prompt when: (a) active topic is completed, or (b) no active topic but queue has items
- Topic page shows next-topic card below completion banner
- Admin klasse_detail shows queue position "(3/7)" next to student's current topic
- **Design decision: queue stays optional** — making it required would only remove ~4 guard clauses but would add setup overhead for simple classes, break per-student assignment overrides, and force migration of existing classes. Queue handles *progression*; manual assignment handles *exceptions*.

### Warmup / Spaced Repetition (Implemented)

Login warm-up + dedicated practice mode for reinforcing previously learned material.

- **Warmup flow:** Login → `/schueler/aufwaermen` → 2 easy questions → if both correct, 2 hard questions → dashboard. Skippable, no grades, once per day.
- **Practice mode:** `/schueler/ueben` — student-initiated from dashboard. Modes: `random`, `schwaechen` (previously incorrect), `thema` (topic filter). 5 questions per session.
- **Question pool:** Built at runtime from `quiz_json` on `task`/`subtask`. Includes completed topics + completed subtasks. Excludes `short_answer` type (too slow for quick sessions).
- **No separate pool table:** Avoids sync problems when teachers edit quizzes.
- **Difficulty model (per-student):** Easy = streak >= 2 OR never seen. Hard = streak < 2 AND seen before. Mixed = no filter.
- **Selection priority:** Previously incorrect → not recently shown (>3 days) → random.
- **DB tables:** `warmup_history` (per-question stats: streak, times_shown/correct, last_shown), `warmup_session` (session log).
- **Grading:** MC: compare index sets. fill_blank: case-insensitive match → LLM fallback (same as `_handle_quiz`). AJAX endpoints, no page reloads.
- **JS-driven:** Questions embedded as JSON in template, one-at-a-time with immediate feedback. Hard questions fetched via AJAX after easy round.

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
| `/schueler/naechstes-thema` | `student_start_next_topic` | POST: start next topic from queue |
| `/schueler/aufwaermen` | `student_warmup` | Warmup: 2 easy + 2 hard questions |
| `/schueler/aufwaermen/antwort` | `student_warmup_answer` | POST (AJAX): grade single warmup answer |
| `/schueler/aufwaermen/weiter` | `student_warmup_continue` | POST (AJAX): get hard questions after easy round |
| `/schueler/aufwaermen/fertig` | `student_warmup_finish` | POST (AJAX): save session stats |
| `/schueler/ueben` | `student_practice` | Practice mode (modes: random, schwaechen, thema) |

**Key helpers in `app.py`:**
- `_resolve_student_topic(student_id, slug)` → resolves slug to `(task, klasse)` by iterating student's classes
- `_resolve_subtask_by_position(subtasks, position)` → returns subtask at 1-based position
- `_handle_quiz(...)` → shared GET/POST quiz logic for both topic and subtask quizzes
- `_build_display_quiz(quiz)` → transforms quiz JSON (`text`/`options`) to template format (`question`/`answers`)
- `_grade_warmup_answer(question, answer)` → grades MC or fill_blank for warmup (with LLM fallback)
- `_serialize_question_for_js(item)` → converts pool item to JSON-safe dict for frontend

**Jinja2 filter:** `{{ task.name|slugify }}` available in all templates for generating slug URLs.

**When adding new student routes:** Use slug/position pattern, resolve to numeric IDs internally for DB operations. Never expose `student_task.id`, `subtask.id`, or `klasse.id` in student-facing URLs.

### Progress Dots and Quiz Dots

The task page shows progress dots: `[task] [?] [task] [task] [?] [topic-quiz?]`

- **Task dots** (`.dot.dot-subtask`): gray (incomplete), green (completed), blue ring (current), `.optional` (dimmed + dashed border for non-required path tasks)
- **Subtask quiz dots** (`.dot.dot-subtask-quiz`): smaller (1.25rem), gray (locked — task not done), amber `.available` (task done, quiz not passed), green `.completed` (passed)
- **Topic quiz dot** (`.dot.dot-quiz`): amber (available), green (passed)
- Progress text ("X von Y Aufgaben erledigt") counts only required `.dot-subtask` elements (not optional, not quiz dots)

## Common Issues and Solutions

### Template Block Structure
Jinja2 templates use `{% block scripts %}` and `{% block content %}` inheritance. The base template wraps `scripts` block with `<script>` tags. Never add additional `<script>` tags inside the block - this creates nested tags and breaks JavaScript execution.

### Unsaved Changes Detection
When tracking form state with `beforeunload` event listener, always update `initialState` after successful save and before reload to prevent false unsaved changes warnings.

### Subtask Editing Cascading Effects
When editing subtasks via `models.update_subtasks()`, be aware of cascading effects:
- Deleting subtasks orphans `quiz_attempt` records → solved by setting `subtask_id=NULL` before delete
- Material-subtask assignments are preserved by matching subtask position/order, not by ID
- Old `subtask_visibility` records are NOT preserved (visibility system replaced by learning paths)

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

### Visual Consistency for Shared Semantics
When adding a new feature that shares semantics with an existing one (e.g. correct/incorrect answers), reuse the exact same visual vocabulary (colors, borders, emojis) rather than inventing new styling. Students instantly understand the new UI without a learning curve. Example: warmup feedback reuses `quiz_result.html` patterns (green/red left borders, ✅/❌, 💬 feedback line, "Deine Antwort" label).

### Database Migrations
For encrypted SQLCipher databases:
- Pass SQLCIPHER_KEY via environment variable
- Migrations must handle both encrypted and unencrypted databases
- Always run migrations BEFORE deploying code changes
- Test migrations locally before production

**See**: Migration scripts in project root (e.g., `migrate_add_time_estimates.py`)
