# Lernmanager - Current State (2026-02-22)

## Latest Session (2026-02-22) — Import Overwrite Mode

### What happened
1. **Import overwrite mode** — When re-importing a topic JSON, you can now choose to overwrite an existing topic instead of creating a duplicate. A dropdown per topic in the preview lets you pick any existing topic as the overwrite target (auto-matched duplicates are pre-selected). Student assignments are preserved, subtasks are updated in-place by position to keep progress intact, and materials are fully replaced.
2. **Optional progress reset** — Per-topic checkbox "Fortschritte zurücksetzen" clears all student progress while keeping assignments.
3. **Completion recalculation** — After overwrite without reset, `student_task.abgeschlossen` is automatically re-evaluated (respects manual admin overrides).

### Files changed
- `models.py` — Added `reset_student_progress_for_task()`, `update_subtasks_from_import()`
- `import_task.py` — Added `overwrite_task_from_import()`, `_replace_materials()`, `_recalculate_completion()`, extracted `_create_materials()` helper
- `app.py` — Updated `_build_topic_preview()` (stores `existing_task_id`), updated import route preview/confirm phases
- `templates/admin/themen_import.html` — Action dropdown, reset checkbox, dynamic JS for button text

### Git state
- Not yet committed

### Next Steps
- Test overwrite flow end-to-end with real data
- **Dashboard Lernfortschritt card** — stats card at bottom of dashboard flow (see `todo.md`)
- **Graded artifact API** — receive grades from grading-with-llm system
- Graded artifact UI (student display, admin grade override)
- Test warmup flow end-to-end with real student data

## Previous Session (2026-02-22) — Quiz Navigation Bugfixes

### What happened
1. **Fix: next button skipped task quizzes** — "Weiter" button on student task view jumped directly to the next task, skipping subtask quizzes. Now checks DOM for unpassed quiz dot before advancing. Also fixed `has_next` template logic so the button stays enabled when current task has an unpassed quiz.
2. **Previous fixes this session** (before this conversation):
   - false unsaved changes warning in admin topic editor
   - quiz result navigation (context-aware buttons after passing/failing quizzes)
   - smarter navigation after passing subtask quiz
   - start next topic directly from quiz result page

### Git state
- All pushed up to `2a7969f` — fix: next button navigates to task quiz before next task
- 5 commits this session: `1f9f2a1`, `a7cc0d9`, `85be1f2`, `3ace883`, `2a7969f`

## Previous Sessions

- **2026-02-21**: Dashboard Description + Layout + Cleanup
- **2026-02-21**: Spaced repetition — login warm-up + practice mode
- **2026-02-21**: Phase 5 sidequests + admin nav cleanup
- **2026-02-15**: Docs, deploy, shared decisions layer
- **2026-02-15**: Phase 4 topic queue, remove prerequisites, web-based topic import
- **2026-02-14**: Phase 3 learning paths + admin visibility overhaul, deployed
- **2026-02-13**: Phase 1+2 migration + shared model foundation
- **2026-02-12**: Per-Aufgabe materials, quizzes, LLM grading, auto-attendance

## Key References

- **Architecture & conventions:** `CLAUDE.md`
- **Shared decisions:** `docs/shared/` (symlink → `~/coding/shared-decisions/`)
- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md`
- **Open tasks:** `todo.md`
