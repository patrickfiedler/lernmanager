# Lernmanager - Current State (2026-02-13)

## Latest Session (2026-02-13) — Admin Simplification Analysis + Phase 0 Cleanup

### Admin simplification analysis
- **`docs/2026-02-13_admin_simplification_analysis.md`** — identified that learning paths eliminate the need for manual subtask visibility management, the legacy `current_subtask_id` system, and the "redirect to config" workflow
- Combined plan updated: `~/.claude/plans/fuzzy-wiggling-unicorn.md` — admin simplification woven into phases 2–5

### Phase 0 cleanup (done)
- **Removed `current_subtask_id` admin system** — `admin_schueler_aufgabe_setzen()` route, `set_current_subtask()` and `get_current_subtask()` model functions, "Aktuelle Aufgabe verwalten" card from student detail page, `loadSubtasksForStudent()` JS, subtask dropdown from individual topic assignment
- **Removed 7 debug prints** from visibility management routes
- **Moved raw SQL** from `admin_aufgaben_verwaltung_speichern()` into model functions (`clear_student_subtask_visibility_override()`, `set_subtask_visibility_for_student()`)
- **Added `subtask_visibility` table** to `init_db()` (was only in migration script)
- Student detail page: 245 → ~148 lines (removed ~100 lines of dead UI + JS)

### Combined plan (updated, not yet implemented)
- **Learning paths + topic progression + sidequests + admin simplification** — `~/.claude/plans/fuzzy-wiggling-unicorn.md`
  - Phase 1: Combined migration (subtask: path/path_model/graded_artifact, student: lernpfad, student_task: drop UNIQUE + rolle + drop current_subtask_id, new topic_queue table)
  - Phase 2: Shared model foundation (INSERT instead of REPLACE, get_all_student_tasks, remove dead code)
  - Phase 3: Learning paths + admin visibility overhaul (path UI, completion logic, remove visibility management pages, simplify student detail page, simplify topic assignment)
  - Phase 4: Topic progression (queue, "click next", admin queue UI)
  - Phase 5: Sidequests + final admin polish (nav cleanup)

### Next Step
- **Implement Phase 1** of the combined plan: write `migrate_paths_and_progression.py` (add path/path_model/graded_artifact to subtask, lernpfad to student, drop UNIQUE + add rolle + drop current_subtask_id on student_task, create topic_queue table, update init_db)
- Read the full plan at `~/.claude/plans/fuzzy-wiggling-unicorn.md` before starting

### Still Pending
- **Deploy to server** — run `update.sh` on the server (1 unpushed commit + uncommitted changes)
- **Manual testing** — slug URLs, quiz dots, subtask toggle flow need browser testing
- **Uncommitted changes:** app.py, models.py, templates/admin/schueler_detail.html, go_on_from_here.md, todo.md, docs/2026-02-13_admin_simplification_analysis.md (new)

### Important: `current_subtask_id` still in DB schema
- The column still exists in `init_db()` and in the live database — will be dropped in Phase 1 migration
- `_advance_to_next_subtask_internal()` still writes to it (harmless, will be cleaned up in Phase 2)
- `assign_task_to_student()` and `assign_task_to_klasse()` still reference it in INSERT statements — will be cleaned up in Phase 2

## Previous Sessions

- **2026-02-13 (earlier)**: Topic progression plan, format docs, curriculum spec, learning paths spec in CLAUDE.md
- **2026-02-13 (earlier)**: Cleanup & push, student view improvements (slug URLs, quiz dots, declutter), admin quiz answer review page
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
