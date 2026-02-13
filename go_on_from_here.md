# Lernmanager - Current State (2026-02-13)

## This Session (2026-02-13) — Student View Improvements (COMPLETE)

Decluttered student view, added quiz dots for subtask quizzes, and replaced all numeric student URLs with human-readable slugs.

### What Was Built

1. **Slug-based URLs** — `utils.py: slugify()` converts topic names to URL-friendly slugs (handles German umlauts: ä→ae, ö→oe, ü→ue). Registered as Jinja2 filter `|slugify`. All student routes rewritten:
   - `/schueler/klasse/1` → `/schueler/thema/bilder-und-pixel`
   - `?subtask_id=377` → `?aufgabe=3` (1-based position)
   - `/schueler/thema/5/quiz` → `/schueler/thema/bilder-und-pixel/quiz`
   - `/schueler/thema/5/aufgabe-quiz/12` → `/schueler/thema/bilder-und-pixel/aufgabe-3/quiz`
   - NEW: `/schueler/thema/<slug>/quiz-ergebnis` and `/schueler/thema/<slug>/aufgabe-<pos>/quiz-ergebnis`

2. **Visual declutter** — Removed breadcrumbs, subject/level info (`Informatik · Klasse 5`), default time estimate fallback ("~15-30 Min"). Replaced Lernziel with "Nächste Aufgabe: [preview]" on dashboard.

3. **Subtask quiz dots** — Progress dots now show: `[task] [?] [task] [task] [?] [topic-quiz?]`. Quiz dots are smaller (1.25rem vs 1.5rem), with states: gray (locked), amber (available), green (passed). Clicking green dot shows past quiz result.

4. **DRY refactoring** — Extracted `_handle_quiz()` shared helper for topic/subtask quiz logic, `_build_display_quiz()` for quiz JSON→template transformation, `_resolve_student_topic()` and `_resolve_subtask_by_position()` route helpers.

### Key Design Decisions

- **Slugs computed on-the-fly**: No DB migration needed — slugify(task['name']) used at runtime
- **Internal IDs preserved**: Routes resolve slug→numeric ID internally, all DB operations unchanged
- **Separate quiz routes**: `student_quiz` (topic) and `student_quiz_subtask` (subtask) replace the old dual-route pattern
- **Removed `partial` dot state**: Subtask dot is green when done; separate quiz dot shows quiz state

### Files Changed

- `utils.py` — Added `slugify()` function
- `app.py` — Rewrote all student routes, added helpers, registered `|slugify` filter
- `templates/student/dashboard.html` — Task preview, slug URLs
- `templates/student/klasse.html` — Quiz dots, slug URLs, simplified JS
- `templates/student/quiz.html` — Slug-based form action and cancel links
- `templates/student/quiz_result.html` — Slug-based retry and back links
- `static/css/style.css` — Quiz dot styles, removed breadcrumb/topic-meta CSS

### Deployment

1. Just run `update.sh` — no migration, no new dependencies

## Previous Session (2026-02-13) — Admin Quiz Answer Review Page (COMPLETE)

Added a read-only admin page at `/admin/quiz-antworten` to review free-text quiz answers (fill_blank, short_answer). Committed and pushed as `c15b63e`.

## Previous Sessions

- **2026-02-12**: Per-Aufgabe material assignments, student CSS fix, per-Aufgabe quizzes, auto-attendance, LLM-graded quizzes
- **2026-02-10**: Bug fixes + performance — broken JS URLs, bot 405 errors, concurrent download perf
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO analysis
- **2026-02-04/05**: UI improvements — subtask visibility, terminology rename, JSON export/import

## Content Restructuring (Separate Project - In Progress)

Task content is being restructured outside the app using the JSON export/import workflow.

## Key References

- **Quiz evolution research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- **Todo list:** `todo.md`
- **Deployment docs:** `CLAUDE.md` (Deployment section)
