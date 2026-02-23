# Lernmanager - Current State (2026-02-23)

## Latest Session (2026-02-23) — AJAX Quiz Dot Fix

### What happened
1. **fix: Next button skips quiz after AJAX checkbox** — After checking a subtask done via AJAX, clicking Next skipped the quiz because `data-quiz-available` was never updated in the DOM. Fixed by updating `quizDot.dataset.quizAvailable = 'true'` and adding `.available` CSS class in `toggleSubtask()` success handler. (`templates/student/klasse.html`)

### Files changed
- `templates/student/klasse.html` — update quiz dot state after AJAX subtask toggle

### Git state
- `518a502` — fix: quiz result missing next-task button (PRG pattern)
- `d607425` — fix: increase waitress connection_limit and threads for class-size load
- **Not yet deployed to production**

### Next Steps
- **Deploy**: `ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'`
- **Dashboard Lernfortschritt card** — stats card at bottom of dashboard flow
- **Graded artifact API** — receive grades from grading-with-llm system

---

## Previous Session (2026-02-23) — Quiz Navigation + Server Config Fixes

### What happened
1. **fix: quiz result missing next-task button (PRG pattern)** — `_handle_quiz` rendered `quiz_result.html` inline after POST without `next_position`, `quiz_bestanden`, `klasse`, `next_topic`. Template fell through to "Zum Themen-Quiz" even mid-topic. Fixed: redirect to dedicated result routes (`student_quiz_result_subtask` / `student_quiz_result`) that already compute full navigation context. Net: -13 lines. (`app.py`)
2. **fix: waitress connection_limit + threads** — Default `connection_limit=100` and `threads=16` saturated under full-class quiz burst. Raised to `connection_limit=500`, `threads=32`. (`run.py`)

### Files changed
- `app.py` — `_handle_quiz` POST now redirects instead of rendering inline
- `run.py` — `connection_limit=500`, `threads=32`

### Git state
- `518a502` — fix: quiz result missing next-task button (PRG pattern)
- `d607425` — fix: increase waitress connection_limit and threads for class-size load

---

## Previous Session (2026-02-23) — Production Bug Fixes

### What happened
1. **fix: Next button skips quiz (JS bug)** — `goToNextSubtask` redirected to quiz even when locked. Fixed with `&& quizAvailable === 'true'`. Side effect tracked in High Priority.
2. **fix: Lernpfad badge showed "Bergweg" for students with no path** — Changed to "Kein Pfad" (gray) when `lernpfad IS NULL`.
3. **feat: Set Lernpfad for whole class** — New form on class detail page. New model `set_class_lernpfad()`. New students now default to `bergweg`.
4. **fix: Duplicate students in class list** — `get_students_in_klasse` LEFT JOIN returned one row per active primary task. Fixed with correlated subquery. Migration `migrate_005_fix_duplicate_tasks.py`. **Deployed and verified.**

### Git state
- Committed and pushed through `060f4c8` — fix: duplicate students in class list
- **Deployed to production.**

---

## Previous Session (2026-02-23) — Align Learning Paths with Shared Decisions

### What happened
1. **Teacher assigns path** — Removed student self-selection. Added admin path assignment dropdown to student detail page.
2. **Student UI shows Pflicht/Zusatz only** — Removed path name badges from student views.
3. **Diamond shape for Zusatz dots** — `transform: rotate(45deg)` for colorblind-accessible distinction.

### Git state
- `f32c14f` — feat: teacher-assigned learning paths with diamond Zusatz dots

---

## Previous Sessions

- **2026-02-22**: Warmup pool bugfix, import overwrite mode, quiz navigation bugfixes
- **2026-02-21**: Dashboard layout, spaced repetition (warmup + practice mode)
- **2026-02-15**: Docs, deploy, shared decisions layer
- **2026-02-15**: Phase 4 topic queue, remove prerequisites, web-based topic import
- **2026-02-14**: Phase 3 learning paths + admin visibility overhaul, deployed
- **2026-02-13**: Phase 1+2 migration + shared model foundation
- **2026-02-12**: Per-Aufgabe materials, quizzes, LLM grading, auto-attendance

## Key References

- **Architecture & conventions:** `CLAUDE.md`
- **Shared decisions:** `docs/shared/` (symlink → `~/coding/shared-decisions/`)
- **Open tasks:** `todo.md`
- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md`
