# Lernmanager - Current State (2026-02-24)

## Latest Session (2026-02-24) — Task page declutter implemented

### What happened
Full implementation of the task page declutter plan:
- `tipps` as a first-class field (migration, models, import, admin editor, student collapsible)
- "Wofür brauchst du das?" demoted from loud top banner to collapsible `<details>` at bottom
- "Ausführliche Beschreibung" removed from student view entirely

### Files changed (uncommitted)
- `migrate_007_add_tipps.py` (new) — DB migration with regex extraction from beschreibung
- `models.py` — `create_subtask`, `update_subtasks`, `update_subtasks_from_import`, `export_task_to_dict`
- `app.py` — admin subtask handler reads `tipps[]`
- `import_task.py` — reads `tipps` from JSON
- `templates/admin/aufgabe_detail.html` — tipps textarea (static list + addSubtask JS)
- `templates/student/klasse.html` — purpose banner removed, tipps collapsible added, Ausführliche Beschreibung removed, why-learn-toggle at bottom
- `static/css/style.css` — `.tipps-toggle` and `.why-learn-toggle` added to collapsible group
- `docs/task_json_format.md` — tipps field documented
- `docs/shared/lernmanager/conventions.md` — tipps field documented
- `docs/shared/mbi/conventions.md` — tipps field noted

### Next Steps
1. **P4 dot legend** — TODO(human) in `templates/student/klasse.html` still open (not a blocker for deploy)
2. **Push + deploy**: `git push` → ssh server → `sudo /opt/lernmanager/deploy/update.sh`
3. **Run migrations on server** (in order): `python migrate_006_add_fertig_wenn.py` then `python migrate_007_add_tipps.py`
4. **Content reauthoring** — move existing `💡 Tipp:` content in MBI JSON files into the new `tipps` field

---

## Previous Session (2026-02-23) — fertig_wenn + UX P0–P7

### What happened
Committed `f608545`:
- `fertig_wenn` as first-class field (migration, models, import, admin editor, student callout)
- UX P0–P7 fixes (color consistency, CTA hierarchy, quiz gating text, dot legend placeholder, quiz anxiety text, easy reading link, post-quiz CTA)
- `list_students.py` helper, `docs/ux_investigation_2026-02.md`
- Dot legend alignment fix (`.progress-dots-column` wrapper)

### Files changed (in commit)
- `migrate_006_add_fertig_wenn.py` (new), `models.py`, `import_task.py`, `app.py`
- `templates/admin/aufgabe_detail.html`, `templates/student/klasse.html`
- `templates/student/dashboard.html`, `quiz.html`, `quiz_result.html`, `warmup.html`
- `static/css/style.css`, `docs/task_json_format.md`
- `docs/ux_investigation_2026-02.md` (new), `docs/ux_questionnaire_2026-02.md` (new)
- `list_students.py` (new), `go_on_from_here.md`, `todo.md`

---

## Previous Sessions (summary)

- **2026-02-23**: db_crypto.py switch op; plain SQLite confirmed as production choice (SQLCipher removed)
- **2026-02-23**: AJAX quiz dot fix, quiz navigation PRG fix, waitress connection_limit fix
- **2026-02-23**: Production bug fixes (path badge, class lernpfad, duplicate students)
- **2026-02-23**: Learning paths aligned with shared decisions (teacher-assigned, diamond Zusatz dots)
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
