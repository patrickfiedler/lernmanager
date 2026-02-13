# Lernmanager - Ideas & Future Plans

## High Priority

- Code Review
- Plan comprehensive simplification and testing of the admin interface: some options like visible tasks hidden behind too many submenus/subpages, some actions fail (moving students), ...

## Bugs

- fix: Make lesson comment saveable without saving student evaluation -> required in case a scheduled lesson does not take place
- ~~fix: compulsory vs optional tasks~~ → superseded by learning paths (path determines required vs. optional)

## Features

- **Topic auto-progression & sidequests** — plan ready, see `~/.claude/plans/fuzzy-wiggling-unicorn.md`. Topic queue per class, student clicks "Next" to advance, unlimited sidequests. Requires schema migration (drop UNIQUE on student_task, add rolle column, new topic_queue table).
- add external API to upload log files from scan-folders.ps1 script -> track student progress from files created on school computers
- **Admin: curriculum alignment page** - Show how topics/tasks map to curriculum learning goals, gaps/overlaps (Priority: Medium)

## Improvements

- Student onboarding page: asks about accessibility preferences (easy reading mode, etc.), reminds when new options available
- Onboarding: preview and choose settings, quick tutorial/guide
- (low priority) Visual learning map of open tasks and connections
- (low priority, performance) DB query optimization: reduce N+1 patterns with encrypted DB → see `query_optimization_analysis.md`
- Admin: batch-import students should include app URL with credentials (hardcode or read from config/headers)
- Admin: allow individual students to see all available tasks (default: only active task)
- Research better place for student self-evaluation (was: student page bottom)
- ~~Multiple active tasks per student for contests/short-term work sprints~~ → covered by topic progression/sidequest plan

## Subtask Management Enhancements

- Add "Activate All Compulsory" button to admin subtask config (requires marking subtasks as compulsory vs. bonus)
- Add "Manage Subtasks" link to admin class detail page
- Show warning on class subtask config if students have individual overrides

## Learning Paths (Spec Ready)

Spec: `docs/2026-02-13_lernmanager_curriculum_spec.md`
Research: `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`

Three cumulative paths: 🟢 Wanderweg (foundational) ⊂ 🔵 Bergweg (full curriculum) ⊂ ⭐ Gipfeltour (everything).
Per-task `path` field = lowest path that includes it. Per-task `path_model`: `skip` (lower paths skip) or `depth` (all paths do it, different grading expectations).

### DB Schema
- [ ] Add `path TEXT` and `path_model TEXT DEFAULT 'skip'` columns to `subtask` table
- [ ] Add `lernpfad TEXT` to `student` table (student's chosen path, default: `bergweg`)
- [ ] Migration script for existing data (set all existing subtasks to `path='wanderweg'`)

### Import
- [ ] `import_task.py`: validate + store `path` and `path_model` fields
- [ ] `import_task.py`: validate + store `graded_artifact` field (see Graded Artifacts below)
- [ ] Update `docs/task_json_format.md` field reference tables

### Student UI — Path Selection
- [ ] Path selection UI (onboarding or settings): student picks Wanderweg/Bergweg/Gipfeltour
- [ ] Allow upgrading path mid-unit (never downgrading)
- [ ] Show current path on dashboard

### Student UI — Task Display
- [ ] Show path markers (🟢/🔵/⭐) on each task dot and in task view
- [ ] Non-required tasks styled as optional (dimmed, labeled "optional für deinen Weg") — NOT hidden
- [ ] All tasks always visible regardless of path

### Progress Tracking
- [ ] `check_task_completion()`: only count path-required tasks for completion
- [ ] Synthesis quiz: unlock after all required tasks for student's path are done
- [ ] Progress dots/text: "X von Y" counts only required tasks for student's path
- [ ] Dashboard progress bar: reflect path-based progress

### Interaction with Existing Features
- **Learning paths take precedence over task visibility.** If a student has a path set, the path determines required/optional. Admin visibility settings (`subtask_visibility`) are overrides for special cases only.
- If nothing else is configured, the student's path is the default — no manual visibility setup needed.
- Students must be able to switch paths easily. Switching path overrides any existing visibility settings.
- Topic queue (auto-progression plan) and prerequisites can coexist — queue sets class schedule, prerequisites act as guards.

## Graded Artifacts (Spec Ready)

Spec: `docs/2026-02-13_lernmanager_curriculum_spec.md` (Section 3)

Some tasks produce graded digital artifacts (documents, images, Scratch projects). ~20 total across the curriculum.

- [ ] Add `graded_artifact_json TEXT` column to `subtask` table (JSON with `keyword`, `format`, `rubric`)
- [ ] Student UI: display artifact keyword and accepted formats
- [ ] Student UI: display grade when available
- [ ] External API endpoint to receive grades from collection/grading script (overlaps with scan-folders.ps1 API todo)
- [ ] Admin UI: view/override artifact grades

## Spaced Repetition (Spec Ready)

Spec: `docs/2026-02-13_lernmanager_curriculum_spec.md` (Section 4.3)

Weekly synthesis quiz (~5 questions) drawn from completed task/topic quiz pools. Low-stakes reinforcement.

- [ ] DB: track question exposure history per student (table: `spaced_repetition_history` or similar)
- [ ] Algorithm: draw from recently completed tasks, prioritize previously incorrect answers
- [ ] New student route + template for weekly quiz
- [ ] Dashboard prompt: "Wochenquiz verfügbar" when due

## New Question Types (Future)

- New question types: true/false, matching, ordering

## UX/Accessibility

**UX Audit:** `docs/archive/2026-01-27_ux_audit/`
**Tier 1:** Complete — See `UX_TIER1_SUMMARY.md`
**Tier 2:** Draft saving, color blindness, practice mode, focus mode
**Tier 3:** Topic→Task→Subtask redesign (5-20 min chunks)

## DSGVO / Datenschutz

See `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md` (Section 5)
- Rechtsgrundlage: Bildungsauftrag (Art. 6 Abs. 1 lit. e), keine Einwilligung nötig
- Informationsschreiben (Entwurf): `docs/vorlagen/informationsschreiben_lernmanager.md`
- [ ] Informationsschreiben vom DSB der Schule prüfen lassen
- [ ] Verarbeitungsverzeichnis aktualisieren
- [ ] Genehmigung der Schulleitung einholen
- [ ] AV-Vertrag mit VPS-Hoster prüfen/abschließen
- [ ] Landesspezifische Schuldatenschutzverordnung prüfen

## Completed (Archive)

<details>
<summary>Click to expand completed items</summary>

- ~~Merge remove-caching branch~~ (caching removed)
- ~~502 error on file upload~~ (DB permissions)
- ~~Error logging~~ (Phase 4, commit bd64505)
- ~~Remove Selbstbewertung from student page~~ (commit 4e64a18)
- ~~Rewrite attendance/evaluation page~~ (commit c8e446f)
- ~~Investigate caching~~ (removed, see caching_investigation.md)
- ~~Claude API for content editing~~ (JSON export/import workflow)
- ~~Student view declutter~~ (breadcrumbs, subject/level, slug URLs, quiz dots)
- ~~Logging: page views + student activities~~ (Phase 5, commit 7720a2a)
- ~~PDF reports: per class + per student~~ (Phase 6, commit 2183568)
- ~~Class schedule~~ (commit eea29d0)
- ~~Auto-attendance~~ (from analytics_events logins)
- ~~LLM grading~~ (llm_grading.py, fill_blank + short_answer)
- ~~Per-task quizzes~~ (quiz_json on subtask table, configurable blocking)
- ~~Per-task materials~~ (checkbox table, backward compatible)
- ~~Student subtask view~~ (commit 9720b41)
- ~~Admin subtask visibility~~ (commit 9720b41)
- ~~Student experience redesign~~ (commit 7253d66, progress dots, purpose banner)
- ~~Performance optimization~~ (commit 721fbc9, Gzip compression)
- ~~Responsive admin menu~~ (commit 67e1a21)
- ~~Favicon~~ (commit 67e1a21)
- ~~Task sorting fix~~ (numerical, not alphabetical)
- ~~Terminology rename~~ (Aufgabe→Thema, Teilaufgabe→Aufgabe)
- ~~Unsaved edits warning~~ (material editor)
- ~~Dashboard visible subtask count~~ (uses get_visible_subtasks_for_student)
- ~~Progress dot current marker~~ (blue ring border)
- ~~Larger progress dots~~ (0.75rem→1.5rem)
- ~~Admin quiz answer review page~~ (commit c15b63e)
</details>
