# Lernmanager - Current State (2026-02-22)

## Latest Session (2026-02-22) — Align Learning Paths with Shared Decisions

### What happened
1. **Teacher assigns path** — Removed student self-selection from Settings page. Added admin path assignment dropdown to student detail page (`POST /admin/schueler/<id>/lernpfad`).
2. **Student UI shows Pflicht/Zusatz only** — Removed path name badges (Wanderweg/Bergweg/Gipfeltour) from student dashboard and task page. Changed "Optional für deinen Weg" → "Zusatz". Updated tooltips and aria-labels.
3. **Diamond shape for Zusatz dots** — Replaced dimming (opacity) with diamond shape (`transform: rotate(45deg)`) for colorblind-accessible distinction. All states (hover, focus, current) preserve the rotation.

### Files changed
- `templates/student/settings.html` — removed Lernpfad section (radio buttons)
- `templates/student/dashboard.html` — removed path badge
- `templates/student/klasse.html` — "Zusatz" labels, cleaned tooltips
- `static/css/style.css` — diamond shape for `.dot.optional`
- `templates/admin/schueler_detail.html` — added Lernpfad dropdown card
- `app.py` — removed student lernpfad POST, added admin lernpfad POST route
- `CLAUDE.md` — updated Learning Paths documentation

### Next Steps
- Verify overwrite flow works in production with real student data
- **Dashboard Lernfortschritt card** — stats card at bottom of dashboard flow (see `todo.md`)
- **Graded artifact API** — receive grades from grading-with-llm system
- Graded artifact UI (student display, admin grade override)
- Test warmup flow end-to-end with real student data

## Previous Session (2026-02-22) — Warmup Pool Bugfix

### What happened
1. **Fix: exclude intro task quizzes from warmup pool** — Every topic now has a 5-minute introductory task (always first by `reihenfolge`). Its quiz asks chapter-specific questions ("Wie heißt das benotete Dokument in diesem Kapitel?") that don't make sense in spaced repetition. Added a subquery to `get_warmup_question_pool()` that excludes the first subtask (lowest `reihenfolge`) per topic from the subtask quiz pool.

### Git state
- Committed and pushed as `a65f973` — fix: exclude intro task quizzes from warmup question pool

## Previous Session (2026-02-22) — Import Overwrite Mode

### What happened
1. **Import overwrite mode** — When re-importing a topic JSON, you can now choose to overwrite an existing topic instead of creating a duplicate. A dropdown per topic in the preview lets you pick any existing topic as the overwrite target (auto-matched duplicates are pre-selected). Student assignments are preserved, subtasks are updated in-place by position to keep progress intact, and materials are fully replaced.
2. **Optional progress reset** — Per-topic checkbox "Fortschritte zurücksetzen" clears all student progress while keeping assignments.
3. **Completion recalculation** — After overwrite without reset, `student_task.abgeschlossen` is automatically re-evaluated (respects manual admin overrides).

### Git state
- Committed and pushed as `727a6b8` — feat: import overwrite mode for topic JSON re-import

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
