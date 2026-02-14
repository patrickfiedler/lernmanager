# Lernmanager - Current State (2026-02-14)

## Latest Session (2026-02-14) — Phase 3 Done

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

### Deploy to server
- Run `deploy/update.sh` — it auto-discovers and runs pending migrations in order:
  1. `migrate_001_paths_and_progression.py`
  2. `migrate_002_add_lernziel_schueler.py`
  3. `migrate_003_add_hidden.py`

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
