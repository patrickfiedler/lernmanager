# Lernmanager - Ideas & Future Plans

## High Priority

- ~~Merge remove-caching branch to main and deploy to server~~ (Complete - merged, caching removed)
- ~~502 error when I try to upload a file~~ (Fixed - was database permissions issue)
- ~~error logging functionality~~ (Complete - Phase 4, commit bd64505)
- ~~Remove "Selbstbewertung pro Unterricht" from student page~~ (Complete - commit 4e64a18)
- ~~student attendance and evaluation page -> completely rewrite this page~~ (Complete - commit c8e446f, new rating system with -, ok, +, pre-defined comments, lesson comments)
- Code Review
- Plan comprehensive simplification and testing of the admin interface: reason some options like visible tasks hidden behind too many submenus/subpages, some actions fail (moving students), ...
- App needs more focus in the student view for the actual task and less visibility for nice-to-have but effectively less important information; also student dashboard does still not make it clear enough where learning actually starts (maybe skip dashboard and display current tasks directly?) -> based on common student feedback "What should I do?"
- ~~Investigate if the caching mechanism is actually worth it~~ (Complete - removed all caching, see caching_investigation.md)
- ~~Investigate Claude Code and/or Claude API support for task editing and rewriting/rearranging existing content~~ (Complete - JSON export/import workflow implemented, content restructuring in progress as separate project)

## Learning Paths & Quiz Evolution (Researched 2026-02-07)
See `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- Learning paths: Wanderweg/Bergweg/Gipfelweg difficulty system with mountain visualization
- Per-task quizzes: add quiz_json to subtask table, quiz after each Aufgabe
- New question types: true/false (free), fill-blank, matching, ordering, short answer
- LLM grading: Claude Haiku API for free-text answers, anonymized, rate-limited, ~$1/class

## UX/Accessibility Improvements
**UX Audit:** `docs/archive/2026-01-27_ux_audit/`
**Tier 1:** ✅ COMPLETE (7/7 tests pass) - See `ux_tier1_complete_summary.md`
**Tier 2:** Draft saving, color blindness, practice mode, focus mode
**Tier 3:** Topic→Task→Subtask redesign (5-20 min chunks)

## Features

- ~~Logging functionality: track number of users and page views~~ (Complete - Phase 5, commit 7720a2a)
- ~~logging functionality #2: track student activities in action log~~ (Complete - Phase 5, commit 7720a2a)
- ~~Student progress reports as PDF file per class: human readable format for quick overview~~ (Complete - Phase 6, commit 2183568)
- ~~student progress reports as PDF file per student: information from class progress report + student's individual activity log~~ (Complete - Phase 6, commit 2183568)
- ~~Add regular class dates for each class (schedule)~~ (Complete - commit eea29d0, implemented in student assessment improvements)
- ~~Auto-attendance from student login data~~ (Complete - auto-fills Unterricht page from analytics_events logins, button + CLI + cron)
- add external API to upload log files from scan-folders.ps1 script -> major feature to track student progress from the files they create on the school computers
- LLM-based grading with Claude Haiku API for free-text answers (fill-blank, short answer, matching) -> see `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
- **Admin: curriculum alignment page** - Show how topics/tasks map to curriculum learning goals, display alignment between app content and official curriculum, helps teachers ensure coverage of required learning objectives, potentially show gaps or overlaps (Priority: Medium - useful for planning and compliance)

## Improvements

- student onboarding page: asks students about their accessibility preferences (easy reading mode, etc.) so students can learn that these options exist; make it so that it reminds students when new accessibility options become available
- onboarding page: preview and choose settings, quick tutorial/guide on how to use
- ~~student view: show only the current (or the first) subtask of the active task~~ (Complete - commit 9720b41, see subtask_implementation_summary.md)
- ~~admin view: assign particular subtasks to classes and to students~~ (Complete - commit 9720b41, see subtask_implementation_summary.md)
- ~~Add #teilaufgabe anchor to student page. If the page reloads after a subtask has been completed, jump to this anchor directly.~~ (Complete - commit 4e64a18)
- ~~Student experience redesign: card-based layout, "Why learn this?" purpose banner, progress dots, collapsible sections~~ (Complete - commit 7253d66, hybrid mockup design implemented)
- ~~Database performance optimization: request-level connection caching~~ (Complete - commit 721fbc9, comprehensive performance optimizations with Flask-Caching, HTTP caching headers, Gzip compression)
- (low priority, optional) student view: show visual learning map of open tasks and how they connect to each other; for the moment only for informational purposes
- (low priority, performance) database query optimization: reduce N+1 query patterns to improve page load times with encrypted database → see query_optimization_analysis.md (admin dashboard: 850ms → 170ms potential, ~4-6 hours effort)
- admin view: when batch-importing students, add the url of the app to each line, along with username and password (either hardcode lernen.mrfiedler.de, or maybe read from configuration or HTML headers?)
- admin view: allow individual students to see all available tasks, but default to the current behaviour (students see only the active task)
- research a better way and place to implement student self-evaluation (was: student page, at bottom)
- How can we show more than one active task to the student at any one time, i.e. to adapt to current special occasions like contests or short-term work sprints to improve marks? -> investigate
- ~~in the student view (next to 0 von 8 Aufgaben erledigt) the current task should have a visible margin or shadow to visually mark where students are~~ (Complete - current dot has colored ring border)
- ~~make admin top menu responsive - becomes crowded at 960px width (half of 1920px screen)~~ (Complete - responsive hamburger menu, commit 67e1a21)
- ~~make progress dots slightly larger (double) in desktop view~~ (Complete - doubled from 0.75rem to 1.5rem, scaled ring + quiz dot)
- ~~add favicon to the app~~ (Complete - commit 67e1a21)
- ~~change workflow from task→task→task→...→quiz to task→quiz→task→quiz→task→...~~ (Complete - per-Aufgabe quizzes with configurable blocking, image support)
- move materials from Thema level to Aufgabe level (currently materials are per-topic, should be per-subtask)


## Subtask Management Enhancements (Test 8 findings)

- Add "Activate All Compulsory" button to admin subtask config page:
  - Requires task editor changes to mark subtasks as compulsory vs. bonus
  - Button enables all compulsory subtasks in one click
  - Useful for quick setup of new class assignments
- Add "Manage Subtasks" link to admin class detail page (like on student detail page)
- Show warning on class subtask config page if students have individual overrides:
  - Display alert box below bulk action buttons (Alle aktivieren/deaktivieren) and above subtask checkboxes
  - Format: "⚠️ X Schüler haben individuelle Einstellungen: [Student names with links]"
  - Include clickable links to each student's individual config page
  - Purpose: Prevent confusion when changing class-wide settings (changes won't affect students with overrides)
- Update student dashboard to show visible subtask count instead of total count (currently shows "Fortschritt 0/8" but should show "0/5" if only 5 visible)

## Bugs

- ~~Fix task sorting: should be 1-2-3-10, not 1-10-2-3 (alphabetical vs numerical)~~ (Fixed)
- ~~Class assessment: make it obvious if data has been saved for a day (currently unclear - shows default 2/3 points for all dates)~~ (Fixed in student assessment improvements)
- ~~fix: consistently rename tasks -> topics and subtasks -> tasks (or their respective German equivalents for the frontend) throughout the whole app~~ (Complete - commits d2fb1f0, 27e1a90: Aufgabe→Thema, Teilaufgabe→Aufgabe)
- fix: Make lesson comment saveable without saving student evaluation -> required in case a scheduled lesson does not take place
- fix: current implementation does not treat compulsory and optional tasks differently, but it should -> there needs to be a clear setting in the task editor, and it should be obvious in the student view (maybe have yellow: open compulsory tasks, green: completed tasks, and rainbow colour spectrum for optional tasks)
- ~~fix: adding a material in the task editor loses unsaved edits without warning~~ (Fixed - added unsaved changes detection and warning dialog)

## DSGVO / Datenschutz
See `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md` (Section 5)
- Rechtsgrundlage: Bildungsauftrag (Art. 6 Abs. 1 lit. e), keine Einwilligung nötig
- Informationsschreiben (Entwurf): `docs/vorlagen/informationsschreiben_lernmanager.md`
- [ ] Informationsschreiben vom DSB der Schule prüfen lassen
- [ ] Verarbeitungsverzeichnis aktualisieren
- [ ] Genehmigung der Schulleitung einholen
- [ ] AV-Vertrag mit VPS-Hoster prüfen/abschließen
- [ ] Landesspezifische Schuldatenschutzverordnung prüfen

## Notes

-
