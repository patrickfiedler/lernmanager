# Lernmanager - Current State (2026-02-15)

## Latest Session (2026-02-15) — Phase 4: Topic Queue

### Topic Queue (Topic Progression)
- **What:** Admins define an optional ordered topic sequence per class. Students self-advance when they complete a topic.
- **DB:** `topic_queue` table already existed from Phase 1 migration. No new migration needed.
- **Models:** 4 new functions in `models.py`: `get_topic_queue()`, `set_topic_queue()`, `get_next_queued_topic()`, `get_queue_position()`
- **Admin:** New route `GET/POST /admin/klasse/<id>/themen-reihenfolge` with up/down/remove/add UI. Queue link button added to klasse_detail. Student table shows "(3/7)" position.
- **Student:** New route `POST /schueler/naechstes-thema`. Dashboard shows "Nächstes Thema" with start button. Topic page shows next-topic card after completion.
- **Design:** Queue is optional — classes without one work exactly as before. No drag-and-drop (up/down buttons instead). One-click start (no preview page).
- **Design decision documented:** Analyzed making queue required — only ~4 guard clauses to remove but significant flexibility loss (per-student overrides, setup overhead, migration burden). Kept optional.

**Files changed:**
- `models.py` — 4 queue functions added before Task Export section (~line 876)
- `app.py` — `admin_topic_queue` route (~line 391), modified `admin_klasse_detail` (~line 251), `student_start_next_topic` route (~line 1874), modified `student_dashboard` (~line 1359), modified `student_klasse` (~line 1497)
- `templates/admin/topic_queue.html` — new template (queue table + add dropdown + JS reordering)
- `templates/admin/klasse_detail.html` — queue link button + position display
- `templates/student/dashboard.html` — next topic prompts (completed + no-active cases)
- `templates/student/klasse.html` — next topic card after completion
- `CLAUDE.md` — documented queue behavior, new route, DB table, design decision

### Git state
- Committed: `1b5de8c` — feat: topic queue for self-paced progression (Phase 4)
- Plus one uncommitted change: design decision note added to CLAUDE.md
- Branch `main` is 3 commits ahead of origin (not pushed)

### Next Steps
- **Phase 5: Sidequests + Polish** — sidequest role, polish
- Graded artifact UI (student display, admin grade override)
- Spaced repetition (weekly quiz from completed pools)
- Per-topic path override (future option)
- **Not yet tested in browser** — manual verification recommended before deploy

## Previous Session (2026-02-15) — Remove Prerequisites

### Prerequisite System Removal
- **Why:** `task_voraussetzung` was built before learning paths existed. `check_voraussetzungen_erfuellt()` was never called anywhere — dead code with a misleading admin UI. Topic queue (Phase 4) handles progression via queue ordering.
- **What was removed:** 5 model functions, admin UI (multi-select dropdowns in create/edit/detail forms), prerequisite display on topic list, import/export handling, validation
- **What was kept:** `task_voraussetzung` DB table (existing data preserved, CREATE TABLE stays in `init_db`)
- **Import compatibility:** Old JSON files with `voraussetzungen` field are silently ignored (no validation error)

**Files changed:**
- `models.py` — deleted 5 prerequisite functions, removed from `export_task_to_dict()`
- `app.py` — removed from `admin_themen`, `admin_thema_neu`, `admin_thema_detail`, `admin_thema_bearbeiten`, `_build_topic_preview`
- `import_task.py` — removed validation block, import block, dry-run/CLI output
- `templates/admin/aufgaben.html` — removed prerequisite display
- `templates/admin/aufgabe_form.html` — removed multi-select dropdown
- `templates/admin/aufgabe_detail.html` — removed multi-select + hidden inputs
- `templates/admin/themen_import.html` — removed preview row
- `CLAUDE.md`, `docs/task_json_format.md`, `docs/2026-02-13_lernmanager_curriculum_spec.md` — updated
- `~/.claude/plans/fuzzy-wiggling-unicorn.md` — added design decision

## Previous Session (2026-02-15) — Web-Based Topic Import

### Admin Topic Import via Web UI
- **Problem:** CLI `import_task.py` can't access encrypted SQLCipher DB on production
- **Solution:** Admin web route `/admin/themen/import` with preview → confirm flow
- Refactored `import_task.py`: `check_duplicate()` and `import_task()` accept optional `warnings` list (CLI keeps printing, web collects)
- Route reuses `validate_task_structure()`, `check_duplicate()`, `import_task()` directly — no code duplication
- Supports both single (`{"task": {...}}`) and bulk (`{"tasks": [...]}`) export formats
- Preview shows: name, fach, stufe, kategorie, subtask count with path breakdown, materials, quizzes, duplicate warnings
- Validated JSON passed via hidden `<textarea>` between preview and confirm (stateless)
- Import button added to admin topic list page next to "Alle exportieren"

**Files changed:**
- `import_task.py` — `warnings` parameter on `check_duplicate()` and `import_task()`
- `app.py` — `_build_topic_preview()` helper + `admin_themen_import` route, import from `import_task`
- `templates/admin/themen_import.html` — new template (upload + preview + confirm)
- `templates/admin/aufgaben.html` — import button

## Previous Session (2026-02-14) — Phase 3 Done

### Phase 3: Learning Paths + Admin Visibility Overhaul (DONE)

**3a: Import & Path fields**
- `validate_task_structure()` — path required, path_model optional, graded_artifact optional
- `create_subtask()` — accepts path, path_model, graded_artifact_json
- `import_task()` — extracts and passes path fields
- `update_subtasks()` — accepts path_list, path_model_list
- `export_task_to_dict()` — includes path, path_model, graded_artifact
- Admin subtask save route — collects path/path_model from form

**3b: Path-based completion logic**
- `PATH_ORDER` constant, `is_subtask_required_for_path()` helper
- `get_visible_subtasks_for_student()` — path-based with `required` flag (legacy fallback preserved)
- `check_task_completion()` — only counts path-required subtasks
- `student_dashboard()` — path-required progress counts
- `student_klasse()` — passes path info + required flag to template

**3c: Student path selection**
- Settings page: radio buttons for 🟢 Wanderweg / 🔵 Bergweg / ⭐ Gipfeltour
- Bidirectional switching (up and down)
- `student_settings()` route handles `lernpfad` field

**3d: Student task display**
- Progress dots: `.optional` class for non-required tasks (dimmed + dashed border)
- "Optional für deinen Weg" badge on non-required tasks
- Progress text counts only required subtasks
- Dashboard: path badge on topic cards

**3e: Admin visibility removal**
- Deleted 4 routes: `admin_aufgaben_verwaltung_klasse/schueler/speichern/reset`
- Deleted template: `templates/admin/teilaufgaben_verwaltung.html` (421 lines)
- Deleted 6 model functions: `get/set/clear/bulk/reset_subtask_visibility*`
- Simplified `update_subtasks()`: removed visibility preservation (kept material assignment preservation)

**3f+3g: Admin page cleanup**
- `schueler_detail.html`: removed visibility card, added path badge
- `klasse_detail.html`: removed subtask dropdown + loadSubtasks() JS, simplified to one dropdown + submit

**Migration: `migrate_003_add_hidden.py`**
- Added `hidden INTEGER DEFAULT 0` to subtask table
- Already run on dev DB

### Migration scripts renamed (commit 333cea5)
- Prefixed with 001/002/003 so `deploy/update.sh` runs them in correct alphabetical order
- No manual SQLCIPHER_KEY handling needed — update.sh reads it from `.env`

### Deployed to production (2026-02-14)
- Migrations run successfully: `migrate_001`, `migrate_002`, `migrate_003`
- Server running on latest commit (333cea5)

### Next Steps
- **Phase 4: Topic Progression** — topic queue, auto-assign next topic
- **Phase 5: Sidequests + Polish** — sidequest role, polish
- Graded artifact UI (student display, admin grade override)
- Spaced repetition (weekly quiz from completed pools)
- Per-topic path override (future option documented in CLAUDE.md)

### Pre-existing issues
- 20 FK violations: orphaned student_task rows referencing deleted topics (harmless test data)

## Previous Sessions

- **2026-02-13**: Phase 1+2 (migration + shared model foundation), dual lernziel support
- **2026-02-13 (earlier)**: Phase 0 cleanup (removed current_subtask_id admin system, debug prints, raw SQL)
- **2026-02-13 (earlier)**: Admin simplification analysis, topic progression plan
- **2026-02-13 (earlier)**: Student view improvements (slug URLs, quiz dots, declutter)
- **2026-02-12**: Per-Aufgabe materials, quizzes, LLM grading, auto-attendance
- **2026-02-10**: Bug fixes + performance
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO

## Key References

- **Combined plan:** `~/.claude/plans/fuzzy-wiggling-unicorn.md` (Phases 4–5 remaining)
- **Architecture & conventions:** `CLAUDE.md`
- **Curriculum spec:** `docs/2026-02-13_lernmanager_curriculum_spec.md`
- **Admin simplification:** `docs/2026-02-13_admin_simplification_analysis.md`
- **Open tasks:** `todo.md`
