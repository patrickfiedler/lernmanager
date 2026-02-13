# Lernmanager - Current State (2026-02-13)

## Latest Session (2026-02-13) — Topic Progression Plan + Format Docs

### Designed (not yet implemented)
- **Topic auto-progression & sidequests** — full plan at `~/.claude/plans/fuzzy-wiggling-unicorn.md`
  - Class-wide topic queue (admin defines order, students self-advance)
  - Student clicks "Start next topic" after completing current one
  - Sidequests: unlimited extra topics alongside primary, assigned by admin
  - Schema migration needed: drop UNIQUE on student_task, add `rolle` column, new `topic_queue` table
  - Backward compatible: classes without a queue work as before

### Curriculum spec integrated
- **`docs/2026-02-13_lernmanager_curriculum_spec.md`** — from content planning project. Defines learning paths (Wanderweg/Bergweg/Gipfeltour), graded artifacts, spaced repetition.
- **`todo.md`** — added structured checklists for: learning paths (DB schema, import, student UI, progress tracking), graded artifacts, spaced repetition
- **`docs/task_json_format.md`** — added learning paths section, `path`/`path_model`/`graded_artifact` fields, updated subtask field reference, updated example JSON to use new format (h3 headings, section markers, path fields). Removed old PFLICHT/FREIWILLIG pattern.
- **`CLAUDE.md`** — added "Content Formatting" + "Learning Paths" subsections under Conventions

### Still Pending
- **Deploy to server** — run `update.sh` on the server
- **Manual testing** — slug URLs, quiz dots, subtask toggle flow need browser testing
- No commits made this session — all doc changes are uncommitted

## Previous Sessions

- **2026-02-13 (earlier)**: Cleanup & push, student view improvements (slug URLs, quiz dots, declutter), admin quiz answer review page
- **2026-02-12**: Per-Aufgabe materials, per-Aufgabe quizzes, LLM-graded quizzes, auto-attendance
- **2026-02-10**: Bug fixes + performance
- **2026-02-07**: Research — learning paths, quiz evolution, DSGVO
- **2026-02-04/05**: UI improvements — subtask visibility, terminology rename, JSON export/import

## Content Restructuring (Separate Project - In Progress)

Task content is being restructured outside the app using the JSON export/import workflow.

## Key References

- **Architecture & conventions:** `CLAUDE.md` (student URL structure, quiz dots, terminology, content formatting, learning paths)
- **Curriculum spec:** `docs/2026-02-13_lernmanager_curriculum_spec.md` (learning paths, graded artifacts, spaced repetition)
- **Content format spec:** `docs/task_json_format.md` (JSON structure, markdown formatting, learning paths fields)
- **Open tasks:** `todo.md` (learning paths checklist, graded artifacts, spaced repetition, topic progression plan)
- **Topic progression plan:** `~/.claude/plans/fuzzy-wiggling-unicorn.md`
- **Quiz evolution research:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md`
