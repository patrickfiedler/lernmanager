# Lernmanager - Ideas & Future Plans

## High Priority

- ~~Code Review / Admin simplification~~ → analysis done (`docs/2026-02-13_admin_simplification_analysis.md`), integrated into combined plan
- ~~Phase 0 cleanup~~ → removed dead `current_subtask_id` system, debug prints, raw SQL in routes, added `subtask_visibility` to `init_db()`

## Bugs

- ~~fix: Make lesson comment saveable without saving student evaluation~~ → dedicated "Kommentar speichern" button + oninput detection
- ~~fix: compulsory vs optional tasks~~ → superseded by learning paths (path determines required vs. optional)

## Features

- **Learning paths + topic progression + sidequests + admin simplification** — combined plan: `~/.claude/plans/fuzzy-wiggling-unicorn.md`. 5 phases: migration → shared model → learning paths + admin overhaul → topic progression → sidequests + polish. **Phases 1–5 done.** ✅
- add external API to receive grading results from grading-with-llm system + upload log files from scan-folders.ps1 script (see `docs/shared/grading-with-llm/conventions.md` for data contract)
- **Admin: curriculum alignment page** - Show how topics/tasks map to curriculum learning goals, gaps/overlaps (Priority: Medium)

## Improvements

- **Dashboard: move Lernfortschritt to bottom card** — replace top-right green button with a card at the end of the dashboard flow. Show key stats (completed topics, streak, etc.), link to PDF report. Keeps dashboard focused on the next task.
- Student onboarding page: asks about accessibility preferences (easy reading mode, etc.), reminds when new options available
- Onboarding: preview and choose settings, quick tutorial/guide
- (low priority) Visual learning map of open tasks and connections
- (low priority, performance) DB query optimization: reduce N+1 patterns with encrypted DB → see `query_optimization_analysis.md`
- Admin: batch-import students should include app URL with credentials (hardcode or read from config/headers)
- Admin: allow individual students to see all available tasks (default: only active task)
- Research better place for student self-evaluation (was: student page bottom)
- ~~Multiple active tasks per student for contests/short-term work sprints~~ → covered by topic progression/sidequest plan

## Subtask Management Enhancements

- ~~Add "Activate All Compulsory" button to admin subtask config~~ → superseded by learning paths
- ~~Add "Manage Subtasks" link to admin class detail page~~ → removed subtask management UI
- ~~Show warning on class subtask config if students have individual overrides~~ → visibility system removed

## Learning Paths (Implemented — Phase 3 Done)

Combined plan: `~/.claude/plans/fuzzy-wiggling-unicorn.md`
Spec: `docs/2026-02-13_lernmanager_curriculum_spec.md`

Three cumulative paths: 🟢 Wanderweg ⊂ 🔵 Bergweg ⊂ ⭐ Gipfeltour. Implemented:
- [x] DB columns: `subtask.path`, `subtask.path_model`, `subtask.hidden`, `student.lernpfad`
- [x] Path-based completion logic (`is_subtask_required_for_path()`)
- [x] Student path selection (Settings page, bidirectional)
- [x] Student UI: optional dot styling, path badges, path-aware progress counts
- [x] Admin: path/path_model dropdowns in subtask editor
- [x] Import/export: path fields validated and round-tripped
- [x] Removed old visibility management (4 routes, 6 model functions, 421-line template)
- [x] Simplified admin class/student detail pages

Future: per-topic path override, graded artifact UI, spaced repetition

## Topic Queue (Implemented — Phase 4 Done)

Optional per-class topic ordering for self-paced progression.
- [x] Model functions: `get_topic_queue()`, `set_topic_queue()`, `get_next_queued_topic()`, `get_queue_position()`
- [x] Admin queue management page (`/admin/klasse/<id>/themen-reihenfolge`)
- [x] Admin klasse_detail: queue link + position display
- [x] Student progression route (`POST /schueler/naechstes-thema`)
- [x] Dashboard + topic page: next-topic prompts

Future: drag-and-drop reordering, queue auto-suggestions

## Graded Artifacts (DB Ready, UI Pending)

Spec: `docs/2026-02-13_lernmanager_curriculum_spec.md` (Section 3)

Some tasks produce graded digital artifacts (documents, images, Scratch projects). ~20 total across the curriculum.

- [x] Add `graded_artifact_json TEXT` column to `subtask` table (JSON with `keyword`, `format`, `rubric`)
- [x] Import/export support for graded_artifact field
- [ ] Student UI: display artifact keyword and accepted formats
- [ ] Student UI: display grade when available
- [ ] External API endpoint to receive grades from grading system — data contract: `docs/shared/grading-with-llm/conventions.md` (per-student JSON, keyword matching)
- [ ] Admin UI: view/override artifact grades

## Spaced Repetition (Implemented — Warmup + Practice)

Spec: `docs/2026-02-13_lernmanager_curriculum_spec.md` (Section 4.3)

Login warm-up (2-4 questions) + dedicated practice mode. Low-stakes, skippable.

- [x] DB: `warmup_history` (per-question stats) + `warmup_session` (session log)
- [x] Migration: `migrate_004_warmup_tables.py`
- [x] Model: pool builder, question selection (3-tier priority), history tracking
- [x] Warmup route: `/schueler/aufwaermen` — 2 easy, optionally 2 hard
- [x] Practice route: `/schueler/ueben` — modes: random, schwaechen, thema
- [x] JS-driven single-page question flow (AJAX grading, no reloads)
- [x] Dashboard: practice button when pool is non-empty
- [x] Login redirects to warmup (skips if already done today or no pool)

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

## Reference Documents

- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md` — teaching philosophy, design decisions, open questions
- **Cross-project decisions:** `docs/shared/` — shared context across Lernmanager, MBI curriculum, grading system
- **Curriculum spec:** `docs/2026-02-13_lernmanager_curriculum_spec.md`
- **Combined plan:** `~/.claude/plans/fuzzy-wiggling-unicorn.md`

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
