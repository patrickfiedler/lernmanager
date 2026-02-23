# Lernmanager - Current State (2026-02-23)

## Latest Session (2026-02-23) — Authoring quality rules + fertig_wenn

### What happened
1. **Actions vs. guidance rule added to shared docs** — `📋 Aufgabe:` steps = required actions only; `💡 Tipp:` = how-to, background, shortcuts. Bad/good example (Strg+S) added to:
   - `docs/shared/lernmanager/conventions.md` — new "Section roles" table
   - `docs/shared/mbi/content-design.md` — new bullet block under Authoring Quality Standards
   - `docs/task_json_format.md` — added to marker table + Trennregel box

### Files changed
- `docs/shared/lernmanager/conventions.md`
- `docs/shared/mbi/content-design.md`
- `docs/task_json_format.md`

### Git state
- **Not yet committed** — includes fertig_wenn feature + authoring quality rules

### Next Steps
1. **Complete P4 dot legend** — TODO(human) in `templates/student/klasse.html` — waiting for human contribution before deploying
2. **Commit** (all current changes: fertig_wenn + authoring docs + P0–P7 UX fixes)
3. **Deploy**: ssh server + `sudo /opt/lernmanager/deploy/update.sh` — migration already ran locally, also run on server: `python migrate_006_add_fertig_wenn.py`
4. **Walkthrough** with anonymized DB (`anonymize_db.py`) + `list_students.py`

---

## Previous Session (2026-02-23) — fertig_wenn as first-class field + visual completion zone

### What happened
1. **`migrate_006_add_fertig_wenn.py`** — adds `fertig_wenn TEXT NULL` to `subtask` table; populates from existing `beschreibung` via regex (strips `✅ Fertig wenn:` section)
2. **`models.py`** — `create_subtask()`, `update_subtasks()`, `update_subtasks_from_import()`, `export_task_to_dict()` all updated with `fertig_wenn` field
3. **`import_task.py`** — create path reads `fertig_wenn` from JSON and passes to `create_subtask()`; overwrite path handled via `update_subtasks_from_import()`
4. **`app.py`** — `admin_thema_aufgaben` handler reads `fertig_wenn[]` from form and passes to `update_subtasks()`
5. **`templates/admin/aufgabe_detail.html`** — added `fertig_wenn` textarea (2 rows) below `beschreibung`, both in the static list and in the `addSubtask()` JS function
6. **`templates/student/klasse.html`** — green callout `.fertig-wenn-callout` shown above checkbox; checkbox gets `.has-fertig-wenn` class when field is set → visually merged completion zone
7. **`static/css/style.css`** — `.fertig-wenn-callout` (green top border, no bottom), `.task-complete.has-fertig-wenn` (green, dashed top border, no top radius) — forms one seamless zone
8. **Docs** — `docs/task_json_format.md`, `docs/shared/lernmanager/conventions.md`, `docs/shared/mbi/conventions.md`, `docs/shared/mbi/content-design.md` updated to reflect `fertig_wenn` as a separate field (not embedded in `beschreibung`)

### Files changed
- `migrate_006_add_fertig_wenn.py` — new
- `models.py` — 4 locations
- `import_task.py` — 1 location (create path)
- `app.py` — admin_thema_aufgaben handler
- `templates/admin/aufgabe_detail.html` — subtask editor + addSubtask() JS
- `templates/student/klasse.html` — completion zone
- `static/css/style.css` — fertig-wenn-callout styles
- `docs/task_json_format.md` — field table + examples
- `docs/shared/lernmanager/conventions.md` — format spec
- `docs/shared/mbi/conventions.md` — measurability rule
- `docs/shared/mbi/content-design.md` — format reference

### Git state
- **Not yet committed** — P4 dot legend TODO(human) still pending

### Next Steps
1. **Complete P4 dot legend** — implement the TODO(human) in `klasse.html`
2. **Run migration** on server: `python migrate_006_add_fertig_wenn.py`
3. **Commit and deploy** after P4 is done
4. **Walkthrough** with `list_students.py` and anonymized DB

---



## Latest Session (2026-02-23) — Student UX Fixes (P0–P7)

### What happened
1. **UX investigation findings document** — `docs/ux_investigation_2026-02.md` — full findings from first classroom lesson + code analysis
2. **P0: Color consistency** — `btn-success` → `btn-primary` on all next-topic CTA buttons; semantic colors (green/amber) reserved for state indicators only
3. **P1: Dashboard CTA hierarchy** — "Weiter lernen →" is now full-width (`btn-block`); practice card demoted to `btn-secondary`
4. **P3: Quiz gating explained** — retry-free note added to subtask quiz card, topic quiz card, and quiz.html intro
5. **P4: Dot legend** — TODO(human) placeholder in `klasse.html` below dot row — pending human contribution
6. **P5: Quiz anxiety** — "retrying is free" message added to quiz_result.html (failed state); warmup subtitle updated to "Kein Druck — das hier wird nicht bewertet"
7. **P6: Easy Reading Mode** — subtle passive link at bottom of dashboard
8. **P7: Post-quiz CTA** — primary buttons on quiz_result.html made full-width + btn-lg
9. **Shared docs** — UX principle added to `lernmanager/pedagogical.md`; authoring quality rules added to `mbi/content-design.md` and `mbi/conventions.md`
10. **list_students.py** — new helper script to list student accounts by state for walkthrough testing

### Files changed
- `static/css/style.css` — `.btn-block`, `.btn-lg` utility classes
- `templates/student/dashboard.html` — P1, P6
- `templates/student/klasse.html` — P3, P4 (TODO placeholder)
- `templates/student/quiz.html` — P3
- `templates/student/quiz_result.html` — P5, P7
- `templates/student/warmup.html` — P5
- `docs/shared/lernmanager/pedagogical.md` — UX design principle
- `docs/shared/mbi/content-design.md` — authoring quality guidelines
- `docs/shared/mbi/conventions.md` — Fertig-wenn measurability rule
- `docs/ux_investigation_2026-02.md` — new findings document
- `list_students.py` — new helper script

### Git state
- **Not yet committed** — waiting for P4 dot legend (TODO(human))

### Next Steps
1. **Complete P4 dot legend** — implement the TODO(human) in `klasse.html`
2. **Commit and deploy** after P4 is done
3. **Walkthrough** with `list_students.py` and anonymized DB



## Latest Session (2026-02-23) — db_crypto.py switch operation

### What happened
1. **feat: db_crypto.py `switch` operation** — auto-detects DB state (`detect_db_state`) and toggles encrypted↔plain in-place. encrypted→plain requires `--key`; plain→encrypted auto-generates key if omitted. Updates `.env` via `_env_disable_key`/`_env_enable_key` (comment-out vs. uncomment/append). All in-place ops now call `_fix_ownership` after rename to restore `lernmanager:lernmanager` ownership after root writes.

### Files changed
- `deploy/db_crypto.py` — added `switch`, `detect_db_state`, `_fix_ownership`, `_env_disable_key`, `_env_enable_key`

### Git state
- Deployed and verified ✓

### Performance Result (2026-02-23)
**Plain SQLite is dramatically faster on a 1-core VPS under concurrent load.**
- DB queries: 0.4–0.6ms median (was ~30s timeouts under class-size burst)
- Page renders: 5–7ms median
- Zero waitress queue warnings over a full lesson with full class
- Root cause: SQLCipher per-page AES on every 4KB page; page cache can't absorb burst on 1 CPU
- **Decision: keep plain SQLite in production.** Disk encryption (LUKS/dm-crypt at OS level) is the right layer for data-at-rest protection, not application-level SQLCipher.
- benchmark_app.py 404 on student task page = expected (uses old numeric ID URL, slugs now required)

### Next Steps
- **Dashboard Lernfortschritt card** — stats card at bottom of dashboard flow
- **Graded artifact API** — receive grades from grading-with-llm system

---

## Previous Session (2026-02-23) — DB Crypto Management Script

### What happened
1. **feat: deploy/db_crypto.py** — unified DB crypto management script with 4 operations: `verify`, `encrypt`, `decrypt`, `rekey`. Full safety flow for modifying operations: stop service → WAL checkpoint → timestamped backup → operate into `.tmp` → verify → atomic rename → start service → rollback on any failure. Key resolution: `--key` CLI > `SQLCIPHER_KEY` env > `/opt/lernmanager/.env`. `rekey` auto-updates `.env` with new key.

---

## Previous Session (2026-02-23) — AJAX Quiz Dot Fix

### What happened
1. **fix: Next button skips quiz after AJAX checkbox** — After checking a subtask done via AJAX, clicking Next skipped the quiz because `data-quiz-available` was never updated in the DOM. Fixed by updating `quizDot.dataset.quizAvailable = 'true'` and adding `.available` CSS class in `toggleSubtask()` success handler. (`templates/student/klasse.html`)

### Files changed
- `templates/student/klasse.html` — update quiz dot state after AJAX subtask toggle

### Git state
- `518a502` — fix: quiz result missing next-task button (PRG pattern)
- `d607425` — fix: increase waitress connection_limit and threads for class-size load
- **Not yet deployed to production**

### Next Steps
- **Deploy**: `ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'`
- **Dashboard Lernfortschritt card** — stats card at bottom of dashboard flow
- **Graded artifact API** — receive grades from grading-with-llm system

---

## Previous Session (2026-02-23) — Quiz Navigation + Server Config Fixes

### What happened
1. **fix: quiz result missing next-task button (PRG pattern)** — `_handle_quiz` rendered `quiz_result.html` inline after POST without `next_position`, `quiz_bestanden`, `klasse`, `next_topic`. Template fell through to "Zum Themen-Quiz" even mid-topic. Fixed: redirect to dedicated result routes (`student_quiz_result_subtask` / `student_quiz_result`) that already compute full navigation context. Net: -13 lines. (`app.py`)
2. **fix: waitress connection_limit + threads** — Default `connection_limit=100` and `threads=16` saturated under full-class quiz burst. Raised to `connection_limit=500`, `threads=32`. (`run.py`)

### Files changed
- `app.py` — `_handle_quiz` POST now redirects instead of rendering inline
- `run.py` — `connection_limit=500`, `threads=32`

### Git state
- `518a502` — fix: quiz result missing next-task button (PRG pattern)
- `d607425` — fix: increase waitress connection_limit and threads for class-size load

---

## Previous Session (2026-02-23) — Production Bug Fixes

### What happened
1. **fix: Next button skips quiz (JS bug)** — `goToNextSubtask` redirected to quiz even when locked. Fixed with `&& quizAvailable === 'true'`. Side effect tracked in High Priority.
2. **fix: Lernpfad badge showed "Bergweg" for students with no path** — Changed to "Kein Pfad" (gray) when `lernpfad IS NULL`.
3. **feat: Set Lernpfad for whole class** — New form on class detail page. New model `set_class_lernpfad()`. New students now default to `bergweg`.
4. **fix: Duplicate students in class list** — `get_students_in_klasse` LEFT JOIN returned one row per active primary task. Fixed with correlated subquery. Migration `migrate_005_fix_duplicate_tasks.py`. **Deployed and verified.**

### Git state
- Committed and pushed through `060f4c8` — fix: duplicate students in class list
- **Deployed to production.**

---

## Previous Session (2026-02-23) — Align Learning Paths with Shared Decisions

### What happened
1. **Teacher assigns path** — Removed student self-selection. Added admin path assignment dropdown to student detail page.
2. **Student UI shows Pflicht/Zusatz only** — Removed path name badges from student views.
3. **Diamond shape for Zusatz dots** — `transform: rotate(45deg)` for colorblind-accessible distinction.

### Git state
- `f32c14f` — feat: teacher-assigned learning paths with diamond Zusatz dots

---

## Previous Sessions

- **2026-02-22**: Warmup pool bugfix, import overwrite mode, quiz navigation bugfixes
- **2026-02-21**: Dashboard layout, spaced repetition (warmup + practice mode)
- **2026-02-15**: Docs, deploy, shared decisions layer
- **2026-02-15**: Phase 4 topic queue, remove prerequisites, web-based topic import
- **2026-02-14**: Phase 3 learning paths + admin visibility overhaul, deployed
- **2026-02-13**: Phase 1+2 migration + shared model foundation
- **2026-02-12**: Per-Aufgabe materials, quizzes, LLM grading, auto-attendance

## Key References

- **Architecture & conventions:** `CLAUDE.md`
- **Shared decisions:** `docs/shared/` (symlink → `~/coding/shared-decisions/`)
- **Open tasks:** `todo.md`
- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md`
