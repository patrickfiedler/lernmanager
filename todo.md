# Lernmanager - Ideas & Future Plans

## High Priority

- Code Review
- Plan comprehensive simplification and testing of the admin interface: some options like visible tasks hidden behind too many submenus/subpages, some actions fail (moving students), ...

## Bugs

- fix: Make lesson comment saveable without saving student evaluation -> required in case a scheduled lesson does not take place
- fix: current implementation does not treat compulsory and optional tasks differently, but it should -> clear setting in task editor, obvious in student view (yellow: open compulsory, green: completed, rainbow: optional)

## Features

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
- Multiple active tasks per student for contests/short-term work sprints → investigate

## Subtask Management Enhancements

- Add "Activate All Compulsory" button to admin subtask config (requires marking subtasks as compulsory vs. bonus)
- Add "Manage Subtasks" link to admin class detail page
- Show warning on class subtask config if students have individual overrides

## Learning Paths (Researched, Not Started)

See `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- Learning paths: Wanderweg/Bergweg/Gipfelweg difficulty system with mountain visualization
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
