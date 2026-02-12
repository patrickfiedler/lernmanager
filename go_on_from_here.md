# Lernmanager - Current State (2026-02-12)

## This Session (2026-02-12) — Per-Aufgabe Quizzes (COMPLETE)

Implemented per-subtask quizzes: students take a quiz after each Aufgabe (subtask), not just at the end of the Thema (topic). Reinforces learning after each step.

### What Was Built

1. **Migration** — `migrate_add_subtask_quizzes.py`: adds `subtask.quiz_json`, `task.subtask_quiz_required`, `quiz_attempt.subtask_id`
2. **models.py** — Updated `update_subtasks` (quiz_json_list param, orphans quiz_attempts), `toggle_student_subtask` (returns quiz_pending flag), `_advance_to_next_subtask_internal` (considers quiz pass state), `check_task_completion` (subtask + topic quizzes, `subtask_id IS NULL` filter for topic quiz), `save_quiz_attempt`/`get_quiz_attempts` (subtask_id param), new `has_passed_subtask_quiz()`, `update_task` (subtask_quiz_required), `get_student_task` (includes subtask_quiz_required)
3. **app.py** — Dual URL quiz route (`/quiz` + `/aufgabe-quiz/<subtask_id>`), toggle route returns `show_quiz`/`quiz_url`, klasse route computes `subtask_quiz_status` + `quiz_bestanden`, admin routes pass `quiz_json[]` and `subtask_quiz_required`
4. **Templates** — Admin: per-subtask quiz textarea in collapsible `<details>`, subtask_quiz_required checkbox. Student klasse: partial (amber) dots, quiz card when erledigt but quiz pending, JS redirect to quiz. Quiz/result: conditional URLs, image support.
5. **CSS** — `.dot.partial` amber style, `.quiz-question-image`/`.quiz-option-image`, `.subtask-quiz-toggle`
6. **Bugfixes** — 80% → 70% text in all templates (actual threshold was already 70%), `quiz_bestanden` now computed in klasse route

### Key Design Decisions

- **Configurable blocking**: `task.subtask_quiz_required` (default 1) — teachers can set quizzes as optional per topic
- **Quiz JSON on subtask**: Same format as topic quiz — reuses grading, shuffling, and display logic
- **Image support**: Questions and options can have optional `image` field (backward compatible)
- **Orphaning on edit**: When subtasks are re-created in the editor, quiz_attempt.subtask_id is set to NULL (preserves attempt history)

### Flow: Student Completes Subtask With Quiz

1. Student checks "Ich habe das geschafft!"
2. JS sends POST to toggle route
3. `toggle_student_subtask()` checks: subtask has quiz_json + task.subtask_quiz_required → returns `quiz_pending: True`
4. Route returns `{show_quiz: True, quiz_url: "/schueler/thema/.../aufgabe-quiz/..."}`
5. JS redirects to quiz page
6. Student takes quiz → if passed, `advance_to_next_subtask()` runs → student moves to next Aufgabe
7. If failed: student stays on same Aufgabe, dot shows amber, quiz card shows retry button

### Not Yet Committed

All changes are local, not yet committed to git.

## Previous Sessions

- **2026-02-12 (earlier)**: Auto-attendance from student login data (complete, committed)
- **2026-02-10**: Bug fixes + performance — broken JS URLs, bot 405 errors, concurrent download perf
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO analysis
- **2026-02-04/05**: UI improvements — subtask visibility, terminology rename, JSON export/import

## Content Restructuring (Separate Project - In Progress)

Task content is being restructured outside the app using the JSON export/import workflow.

## Uncommitted Files

Untracked docs/scripts from previous sessions (not yet committed):
- `docs/research/`, `docs/vorlagen/`, `docs/plans/`
- `BRANCHING_STRATEGY.md`, `caching_removal_summary.md`, `go_on_from_here.md`
- `debug_deployment.sh`, `fix_redirect_loop.sh`, `debug_auto_attendance.py`
- `migrate_clean_subtask_titles.py`, `migrate_normalize_markdown.py`, `migrate_add_subtask_quizzes.py`
- `2026-02-05 - themen_export.json`

## Deployment Status

Previous code changes pushed to GitHub. Per-Aufgabe quiz feature not yet committed.
- Run `migrate_add_subtask_quizzes.py` BEFORE deploying code changes
- One-time manual nginx update for X-Accel-Redirect still pending (see commit `c6df8da`)

## Key References

- **Quiz evolution research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- **Todo list:** `todo.md`
- **Deployment docs:** `CLAUDE.md` (Deployment section)
