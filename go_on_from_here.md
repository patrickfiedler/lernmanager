# Lernmanager - Current State (2026-02-21)

## Latest Session (2026-02-21) — Spaced Repetition: Warmup + Practice Mode

### What happened
1. **Login warm-up** — after login, students see 2 easy review questions from completed topics/tasks. If both correct, 2 harder questions follow. Completely skippable, no grades. Skipped if already done today or no question pool.
2. **Practice mode** — student-initiated from dashboard. Three modes: random, schwaechen (previously incorrect), nach Thema (topic filter). 5 questions per session.
3. **Question pool built at runtime** from `quiz_json` on `task`/`subtask` tables — no sync problems when teachers edit quizzes. `short_answer` excluded (too slow for quick sessions).
4. **Spaced repetition heuristic** — `warmup_history` tracks per-question streak, times shown/correct, last shown. 3-tier priority: previously incorrect → not recently shown → random. No SM-2 (overkill for 2-4 questions per irregular session).
5. **JS-driven single-page flow** — questions embedded as JSON, graded via AJAX, no page reloads between questions. Same endpoint for warmup and practice grading.
6. **CSS cache busting removed** — dropped `?v=` from `base.html`, removed `immutable` from `deploy/nginx.conf`. `expires 1d` alone is sufficient.

### New files
- `migrate_004_warmup_tables.py` — creates `warmup_history` + `warmup_session`
- `templates/student/warmup.html` — warmup page with JS question flow
- `templates/student/practice.html` — practice mode with mode tabs

### Files changed
- `models.py` — warmup tables in `init_db()`, 7 new functions (pool, selection, priority, history, session, today-check)
- `app.py` — login redirect → warmup, 6 new routes, `_grade_warmup_answer` + `_serialize_question_for_js` helpers, dashboard passes `has_warmup_pool`
- `templates/student/dashboard.html` — practice button card
- `templates/base.html` — removed CSS version query string
- `static/css/style.css` — `.warmup-feedback`, `.warmup-correct/incorrect`, `.warmup-summary`
- `deploy/nginx.conf` — removed `immutable` from static Cache-Control
- `todo.md` — spaced repetition section updated to implemented
- `CLAUDE.md` — warmup routes, section, helpers documented

### Git state
- Committed + pushed: `fb2a725` — feat: spaced repetition — login warm-up + practice mode
- **Deployment pending:**
  1. Run `python migrate_004_warmup_tables.py` on server (creates 2 tables)
  2. Run `sudo /opt/lernmanager/deploy/update.sh`
  3. Manually update nginx: remove `immutable` from static files Cache-Control, reload nginx

### Next Steps
- **Deploy** warmup + practice to production
- **Graded artifact API** — receive grades from grading-with-llm system
- Graded artifact UI (student display, admin grade override)
- Test warmup flow end-to-end with real student data

## Previous Session (2026-02-21) — Phase 5: Sidequests + Admin Nav

### What happened
1. **Sidequests activated** — sidequest cards on dashboard, role selection in admin assignment form
2. **Admin nav cleanup** — 3 items + "Mehr ▾" dropdown

### Git state
- Pushed: `757c426` — fix: curate animal list for student usernames

## Previous Sessions

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
