# Lernmanager - Ideas & Future Plans

## High Priority

- ~~502 error when I try to upload a file~~ (Fixed - was database permissions issue)
- ~~error logging functionality~~ (Complete - Phase 4, commit bd64505)
- ~~Remove "Selbstbewertung pro Unterricht" from student page~~ (Complete - commit 4e64a18)
- ~~student attendance and evaluation page -> completely rewrite this page~~ (Complete - commit c8e446f, new rating system with -, ok, +, pre-defined comments, lesson comments)
- Code Review

## Features

- ~~Logging functionality: track number of users and page views~~ (Complete - Phase 5, commit 7720a2a)
- ~~logging functionality #2: track student activities in action log~~ (Complete - Phase 5, commit 7720a2a)
- ~~Student progress reports as PDF file per class: human readable format for quick overview~~ (Complete - Phase 6, commit 2183568)
- ~~student progress reports as PDF file per student: information from class progress report + student's individual activity log~~ (Complete - Phase 6, commit 2183568)
- ~~Add regular class dates for each class (schedule)~~ (Complete - commit eea29d0, implemented in student assessment improvements)
- add external API to upload log files from scan-folders.ps1 script -> major feature to track student progress from the files they create on the school computers
- later: add AI enabled grading workflow -> needs lots of investigation and testing
- **Admin: curriculum alignment page** - Show how topics/tasks map to curriculum learning goals, display alignment between app content and official curriculum, helps teachers ensure coverage of required learning objectives, potentially show gaps or overlaps (Priority: Medium - useful for planning and compliance)

## Improvements

- ~~student view: show only the current (or the first) subtask of the active task~~ (Complete - commit 9720b41, see subtask_implementation_summary.md)
- ~~admin view: assign particular subtasks to classes and to students~~ (Complete - commit 9720b41, see subtask_implementation_summary.md)
- ~~Add #teilaufgabe anchor to student page. If the page reloads after a subtask has been completed, jump to this anchor directly.~~ (Complete - commit 4e64a18)
- ~~Student experience redesign: card-based layout, "Why learn this?" purpose banner, progress dots, collapsible sections~~ (Complete - commit 7253d66, hybrid mockup design implemented)
- ~~Database performance optimization: request-level connection caching~~ (Complete - commit 721fbc9, comprehensive performance optimizations with Flask-Caching, HTTP caching headers, Gzip compression)
- (low priority, optional) student view: show visual learning map of open tasks and how they connect to each other; for the moment only for informational purposes
- admin view: when batch-importing students, add the url of the app to each line, along with username and password (either hardcode lernen.mrfiedler.de, or maybe read from configuration or HTML headers?)
- admin view: allow individual students to see all available tasks, but default to the current behaviour (students see only the active task)
- research a better way and place to implement student self-evaluation (was: student page, at bottom)
- ~~in the student view (next to 0 von 8 Aufgaben erledigt) the current task should have a visible margin or shadow to visually mark where students are~~ (Complete - current dot has colored ring border)
- make admin top menu responsive - becomes crowded at 960px width (half of 1920px screen)
- replace timestamp URL parameter cache-busting with Cache-Control headers (cleaner, no URL pollution) - see frontend_patterns.md for implementation


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
- fix: consistently rename tasks -> topics and subtasks -> tasks (or their respective German equivalents for the frontend) throughout the whole app
- fix: Make lesson comment saveable without saving student evaluation -> required in case a scheduled lesson does not take place
- fix: current implementation does not treat compulsory and optional tasks differently, but it should -> there needs to be a clear setting in the task editor, and it should be obvious in the student view (maybe have yellow: open compulsory tasks, green: completed tasks, and rainbow colour spectrum for optional tasks)

## Notes

-
