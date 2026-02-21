# Lernmanager - Current State (2026-02-21)

## Latest Session (2026-02-21) — Phase 5: Sidequests + Admin Nav

### What happened
1. **Sidequests activated** — the `rolle` column was already in the DB and `assign_task_to_student()` already accepted it. Added the missing UI pieces:
   - `get_student_sidequests(student_id, klasse_id)` in `models.py` — queries active sidequest rows
   - `student_dashboard()` in `app.py` — fetches sidequests per class, passes `sidequests_by_klasse` to template
   - `admin_schueler_thema_zuweisen()` in `app.py` — reads `rolle` from form, passes to model
   - `templates/student/dashboard.html` — sidequest cards (⚔️ badge, amber/orange) rendered below primary card
   - `templates/admin/schueler_detail.html` — Hauptthema/Sidequest radio group in assignment form
2. **Admin nav cleanup** — reduced 8 nav items to 3 + "Mehr ▾" dropdown
   - `templates/base.html` — `<details>`/`<summary>` CSS-only dropdown (no JS)
   - `static/css/style.css` — `.nav-dropdown` + `.nav-dropdown-menu` styles + mobile overrides

### Files changed
- `models.py` — added `get_student_sidequests()`
- `app.py` — updated `student_dashboard()`, `admin_schueler_thema_zuweisen()`
- `templates/student/dashboard.html` — sidequest cards
- `templates/admin/schueler_detail.html` — role radio buttons
- `templates/base.html` — "Mehr ▾" dropdown nav
- `static/css/style.css` — dropdown CSS

### Git state
- Uncommitted changes: all 6 files above
- Next: commit, push, deploy

### Next Steps
- **Commit + deploy** Phase 5
- **Graded artifact API** — receive grades from grading-with-llm system
- Graded artifact UI (student display, admin grade override)
- Spaced repetition (weekly quiz from completed pools)
- Lesson comment fix (saveable without evaluation)

## Previous Session (2026-02-15) — Docs, Deploy, Shared Decisions

### What happened
1. **Pedagogical decisions documented** — created `docs/pedagogy/pedagogical_decisions.md`
2. **Committed and pushed** all pending changes (4 commits total, including Phase 4 topic queue)
3. **Deployed to production** — teacher is testing with new MBI curriculum content
4. **Shared decisions layer created** — `~/coding/shared-decisions/` with 3 project subfolders, symlinked at `docs/shared/`

### Git state
- Last pushed: `a5e4704` — docs: move pedagogy file, add shared-decisions symlink, update cross-project refs

## Previous Sessions

- **2026-02-15**: Phase 4 topic queue, remove prerequisites, web-based topic import
- **2026-02-14**: Phase 3 learning paths + admin visibility overhaul, deployed
- **2026-02-13**: Phase 1+2 migration + shared model foundation
- **2026-02-13 (earlier)**: Phase 0 cleanup, admin simplification, student view improvements
- **2026-02-12**: Per-Aufgabe materials, quizzes, LLM grading, auto-attendance

## Key References

- **Architecture & conventions:** `CLAUDE.md`
- **Shared decisions:** `docs/shared/` (symlink → `~/coding/shared-decisions/`)
- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md`
- **Open tasks:** `todo.md`
