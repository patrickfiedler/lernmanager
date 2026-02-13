# Lernmanager - Current State (2026-02-13)

## Latest Session (2026-02-13) — Cleanup & Push

All changes pushed to origin. No migration needed, no new dependencies.

### Commits Pushed
- `c2305c0` fix: harmonize quiz result display and use floor-based pass threshold
- `d4ac08e` feat: support subtask quizzes in import/export, add JSON format docs
- `bce06d0` feat: declutter student view, add quiz dots, use slug-based URLs
- `ba281e0` chore: add favicon
- `25c41eb` chore: add project docs, migration scripts, and test data

### Cleanup Done
- Deleted 7 temp files (debug scripts, screenshots, temp exports, obsolete docs)
- Committed docs/, migration scripts, and test data

### Not Yet Done
- **Deploy to server** — run `update.sh` on the server
- **Manual testing** — slug URLs, quiz dots, subtask toggle flow need browser testing

## Previous Sessions

- **2026-02-13 (earlier)**: Student view improvements (slug URLs, quiz dots, declutter), admin quiz answer review page
- **2026-02-12**: Per-Aufgabe materials, per-Aufgabe quizzes, LLM-graded quizzes, auto-attendance
- **2026-02-10**: Bug fixes + performance
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO
- **2026-02-04/05**: UI improvements — subtask visibility, terminology rename, JSON export/import

## Content Restructuring (Separate Project - In Progress)

Task content is being restructured outside the app using the JSON export/import workflow.

## Key References

- **Architecture & conventions:** `CLAUDE.md` (student URL structure, quiz dots, terminology)
- **Open tasks:** `todo.md` (High Priority: code review, admin simplification)
- **Quiz evolution research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
