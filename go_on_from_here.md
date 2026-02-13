# Lernmanager - Current State (2026-02-13)

## Latest Session (2026-02-13) — Phase 1 Done, Phase 2 In Progress

### Phase 1: Combined Migration (DONE)
- **`migrate_paths_and_progression.py`** — written and tested on dev DB
  - `subtask`: +path, +path_model, +graded_artifact_json (80 existing subtasks set to `path='wanderweg'`)
  - `student`: +lernpfad (default: bergweg)
  - `student_task`: recreated — dropped UNIQUE(student_id, klasse_id), dropped current_subtask_id, added rolle (24 rows preserved)
  - New `topic_queue` table created
- **`init_db()`** updated in models.py to match new schema
- Commit `b3acd80`: Phase 0 cleanup (committed this session)
- **20 pre-existing FK violations** found (orphaned student_task rows referencing deleted topics) — not caused by migration, harmless test data

### Phase 2: Shared Model Foundation (IN PROGRESS)
Completed so far:
- **`get_student_task()`** — added `AND abgeschlossen=0 AND rolle='primary' LIMIT 1`
- **`get_all_student_tasks()`** — NEW function, returns all rows (active + completed, all roles) for slug resolution
- **`get_students_in_klasse()`** — added `AND st.abgeschlossen=0 AND st.rolle='primary'` to LEFT JOIN
- **`_resolve_student_topic()`** (app.py) — now uses `get_all_student_tasks()` to search all student_task rows
- **`_advance_to_next_subtask_internal()`** — removed `current_subtask_id` references (SELECT and UPDATE)

### WAITING FOR HUMAN INPUT
- **`assign_task_to_student()`** has a `TODO(human)` placeholder — user needs to implement the core assignment logic (3 steps: deactivate existing primary, skip duplicates, INSERT new row)
- After that: `assign_task_to_klasse()` needs same pattern applied
- Then: verify app still works, commit Phase 2

### Still TODO for Phase 2
- [ ] Human implements `assign_task_to_student()` body
- [ ] Update `assign_task_to_klasse()` with same pattern (loop over students)
- [ ] Verify app starts and basic flows work
- [ ] Commit Phase 2

### Uncommitted changes
- `app.py` — `_resolve_student_topic()` uses `get_all_student_tasks()`
- `models.py` — Phase 2 model changes + init_db schema updates
- `templates/admin/schueler_detail.html` — Phase 0 cleanup (already committed)
- `migrate_paths_and_progression.py` — new migration script
- `go_on_from_here.md`, `todo.md`
- `docs/2026-02-13_admin_simplification_analysis.md`

### Deploy to server
- 2 unpushed commits + uncommitted Phase 2 changes
- Run `update.sh` on server after Phase 2 is committed
- Must run `migrate_paths_and_progression.py` on server BEFORE deploying code

## Combined Plan (Phases 3–5 not yet started)
- **`~/.claude/plans/fuzzy-wiggling-unicorn.md`** — full 5-phase plan
- Phase 3: Learning paths + admin visibility overhaul
- Phase 4: Topic progression (queue, "click next", admin queue UI)
- Phase 5: Sidequests + final admin polish

## Previous Sessions

- **2026-02-13 (earlier)**: Admin simplification analysis, Phase 0 cleanup (removed current_subtask_id admin system, debug prints, raw SQL)
- **2026-02-13 (earlier)**: Topic progression plan, format docs, curriculum spec, learning paths spec
- **2026-02-13 (earlier)**: Cleanup & push, student view improvements (slug URLs, quiz dots, declutter)
- **2026-02-12**: Per-Aufgabe materials, per-Aufgabe quizzes, LLM-graded quizzes, auto-attendance
- **2026-02-10**: Bug fixes + performance
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO
- **2026-02-04/05**: UI improvements — subtask visibility, terminology rename, JSON export/import

## Content Restructuring (Separate Project - In Progress)

Task content is being restructured outside the app using the JSON export/import workflow.

## Key References

- **Architecture & conventions:** `CLAUDE.md` (student URL structure, quiz dots, terminology, content formatting, learning paths)
- **Curriculum spec:** `docs/2026-02-13_lernmanager_curriculum_spec.md` (learning paths, graded artifacts, spaced repetition)
- **Content format spec:** `docs/task_json_format.md` (JSON structure, markdown formatting, learning paths fields)
- **Admin simplification:** `docs/2026-02-13_admin_simplification_analysis.md`
- **Open tasks:** `todo.md` (learning paths checklist, graded artifacts, spaced repetition, topic progression plan)
- **Combined plan (paths + progression + sidequests + admin simplification):** `~/.claude/plans/fuzzy-wiggling-unicorn.md`
- **Quiz evolution research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
