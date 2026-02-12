# Lernmanager - Current State (2026-02-12)

## This Session (2026-02-12) — Auto-Attendance Feature (COMPLETE)

Implemented auto-attendance from student login data. Uses `analytics_events` login records + `class_schedule` to auto-fill the Unterricht attendance page.

### What Was Built

1. **models.py** — `auto_fill_attendance(klasse_id, datum)` checks `analytics_events` for student logins between 07:30–16:00, marks present/absent with `has_been_saved=2`. `auto_fill_all_scheduled_today()` runs for all classes scheduled on the current weekday.
2. **app.py** — `POST /admin/klasse/<id>/unterricht/<datum>/auto-attendance` AJAX route + `flask auto-attendance` CLI command for cron jobs.
3. **templates/admin/unterricht.html** — "Auto-Anwesenheit" button (shown when unsaved rows exist), purple left-border indicator for auto-filled rows, dedicated status message for auto-filled state.

### Key Design: Tri-State `has_been_saved`

- `0` = untouched defaults (not yet saved)
- `1` = manually saved by admin
- `2` = auto-filled from login data

No schema migration needed. Auto-fill only processes `0`, so manual saves and previous auto-fills are never overwritten.

### Cron Job (To Be Set Up on Server)

```
15 16 * * 1-5 cd /opt/lernmanager && FLASK_APP=app.py venv/bin/flask auto-attendance >> /var/log/lernmanager/auto-attendance.log 2>&1
```

### Not Yet Committed

- `debug_auto_attendance.py` — debug/inspection script (can be deleted or kept as a utility)

## Previous Sessions

- **2026-02-10**: Bug fixes + performance — broken JS URLs, bot 405 errors, concurrent download perf (commits `27e1a90`, `df9cb65`, `c6df8da`). Started auto-attendance scaffolding.
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO analysis
- **2026-02-04/05**: UI improvements — subtask visibility, terminology rename, JSON export/import

## Content Restructuring (Separate Project - In Progress)

Task content is being restructured outside the app using the JSON export/import workflow.

## Uncommitted Files

Untracked docs/scripts from previous sessions (not yet committed):
- `docs/research/`, `docs/vorlagen/`, `docs/plans/`
- `BRANCHING_STRATEGY.md`, `caching_removal_summary.md`, `go_on_from_here.md`
- `debug_deployment.sh`, `fix_redirect_loop.sh`
- `migrate_clean_subtask_titles.py`, `migrate_normalize_markdown.py`
- `2026-02-05 - themen_export.json`

## Deployment Status

Previous code changes pushed to GitHub. Auto-attendance feature not yet committed.
- One-time manual nginx update for X-Accel-Redirect still pending (see commit `c6df8da`)

## Key References

- **Auto-attendance plan:** was discussed in planning session (plan transcript: `4bebec56-31e3-4082-8acf-8e2a3de5d77b.jsonl`)
- **Feature research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- **Todo list:** `todo.md`
- **Deployment docs:** `CLAUDE.md` (Deployment section)
