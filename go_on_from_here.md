# Lernmanager - Current State (2026-02-12)

## This Session (2026-02-12) — LLM-Graded Quizzes (COMPLETE)

Added free-text quiz question types (`fill_blank`, `short_answer`) graded by LLM (Claude Haiku or local Ollama). Backward compatible — existing MC quizzes unaffected.

### What Was Built

1. **`llm_grading.py`** (new) — LLM grading module. `grade_answer()` calls Anthropic/Ollama API, returns `{correct, feedback, source}`. Fallback gives the point + teacher review message if API unreachable.
2. **`config.py`** — `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT`, `LLM_MAX_CALLS_PER_STUDENT_PER_HOUR`, `LLM_ENABLED`
3. **`models.py`** — `llm_usage` table in `init_db()`, `check_llm_rate_limit()`, `record_llm_usage()`
4. **`migrate_add_llm_usage.py`** (new) — Migration for `llm_usage` table
5. **`app.py`** — `student_quiz()` type-aware grading: MC (unchanged), `fill_blank` (string match → LLM fallback), `short_answer` (always LLM). Rate-limit filtering on GET removes LLM questions when limit exceeded.
6. **`templates/student/quiz.html`** — Text input for `fill_blank`, textarea for `short_answer`
7. **`templates/student/quiz_result.html`** — Shows student text, LLM feedback with color coding, fallback styling
8. **`import_task.py`** — Type-aware validation: `fill_blank` needs `answers` list, `short_answer` needs `rubric`
9. **`requirements.txt`** — Added `anthropic>=0.40`

### Quiz JSON Format (Extended)

```json
{"questions": [
  {"text": "Hauptstadt?", "options": ["Berlin", "München"], "correct": [0]},
  {"type": "fill_blank", "text": "Die Hauptstadt ist ___.", "answers": ["Berlin", "berlin"]},
  {"type": "short_answer", "text": "Erkläre den Wasserkreislauf.", "rubric": "Verdunstung, Kondensation, Niederschlag"}
]}
```

### Key Design Decisions

- **Backward compatible**: Missing `type` = `multiple_choice` (existing behavior unchanged)
- **Anonymized API**: Only question text, rubric, and student answer sent to LLM — never any student metadata
- **Backend swappable**: Anthropic cloud and Ollama use same `anthropic` SDK, switch via 2 env vars
- **Graceful fallback**: API failure → point counted + teacher review message → student never blocked
- **Rate limiting**: Per-student hourly limit (default 20), exceeding limit → LLM questions filtered from quiz
- **fill_blank optimization**: Exact string match first (free), LLM only on mismatch

### Deployment

1. Set env vars: `LLM_API_KEY` (required), optionally `LLM_BASE_URL` and `LLM_MODEL`
2. Run `migrate_add_llm_usage.py` BEFORE deploying
3. `pip install anthropic` (via requirements.txt)
4. Deploy code changes
5. **Dev mode**: Works without API key — `fill_blank` = string match only, `short_answer` = fallback

## Previous Session (2026-02-12) — Per-Aufgabe Material Assignments + CSS Fix

### Per-Aufgabe Material Assignments (COMPLETE)

Implemented per-Aufgabe material assignments: admins can assign materials to specific Aufgaben via a checkbox table, so students only see materials relevant to the Aufgabe they're working on.

#### What Was Built

1. **Migration** — `migrate_add_material_subtask.py`: creates `material_subtask` join table
2. **models.py** — `material_subtask` table in `init_db()`, 3 new functions: `get_materials_for_subtask()`, `get_material_subtask_assignments()`, `set_material_subtask_assignments()`. Updated `update_subtasks()` (preserves assignments by position), `export_task_to_dict()` (includes `subtask_indices`)
3. **app.py** — Updated `admin_thema_detail` (passes assignments to template), new `admin_material_zuordnung` POST route (~line 718), updated `student_klasse` (filters materials by current Aufgabe, ~line 1400)
4. **Template** — `templates/admin/aufgabe_detail.html`: checkbox table with per-material rows and per-Aufgabe columns, "Alle" toggle, JS helpers (`toggleAllForMaterial`, `handleAssignmentChange`)
5. **import_task.py** — Handles `subtask_indices` to restore material-subtask assignments on import

#### Key Design Decisions

- **Backward compatible**: No rows in `material_subtask` = material visible everywhere (existing data just works)
- **Materials stay on Thema**: `material.task_id` FK unchanged. The join table controls *visibility* per Aufgabe
- **Position-based preservation**: When editing subtasks, material assignments are preserved by `reihenfolge` position (same pattern as `subtask_visibility`)
- **Export/import round-trip**: `subtask_indices` (list of reihenfolge positions) included per material in export

#### Bugs Fixed During Implementation

- Jinja2 `set()` is not available — used `[]` (empty list) as default instead in template
- Reverted accidental `<details>` conversion of admin Materials card (was only needed for student view)

### Student View CSS Fix (COMPLETE)

Fixed `.materials-toggle` in student view so the clickable summary header and expandable content appear as one unified box:
- **`static/css/style.css`**: When `[open]`, summary gets flat bottom corners + no bottom border; content gets flat top corners + no top border. Removed `margin-top: 1.5rem` gap from `.materials-content`.

### Not Yet Committed

All changes from this session AND previous per-Aufgabe quizzes session are local, not yet committed.

### Deployment (both features)

1. Run `migrate_add_subtask_quizzes.py` BEFORE deploying
2. Run `migrate_add_material_subtask.py` BEFORE deploying
3. Deploy code changes
4. One-time manual nginx update for X-Accel-Redirect still pending (see commit `c6df8da`)

## Previous Session (2026-02-12) — Per-Aufgabe Quizzes (COMPLETE)

Implemented per-subtask quizzes: students take a quiz after each Aufgabe (subtask), not just at the end of the Thema (topic). Key files: `migrate_add_subtask_quizzes.py`, `models.py`, `app.py`, templates (admin + student), CSS.

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
- `migrate_add_material_subtask.py`
- `2026-02-05 - themen_export.json`

## Key References

- **Quiz evolution research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- **Todo list:** `todo.md`
- **Deployment docs:** `CLAUDE.md` (Deployment section)
