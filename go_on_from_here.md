# Lernmanager - Current State (2026-03-03)

## Latest Session (2026-03-03) — Seilbahn import bugfix

**Bugfix**: `import_task.py:110` — `VALID_PATHS` tuple did not include `'seilbahn'`, causing import validation to fail for any JSON with seilbahn subtasks. One-line fix.

- `import_task.py`: `VALID_PATHS = ('wanderweg', 'bergweg', 'gipfeltour', 'seilbahn')`

Not yet committed. Change is tiny and trivial.

### Git state
- Uncommitted: `docs/vorlagen/informationsschreiben_lernmanager.md` (partial DSGVO update — separate task)
- Uncommitted: `import_task.py` (Seilbahn path fix)
- Pending server migrations still unrun: `migrate_006` → `migrate_007` → `migrate_008`

---

## Previous Session (2026-03-02b) — Seilbahn path support

**Seilbahn added as fourth, non-cumulative learning path** (commit `2d71cef`, pushed):
- `models.py`: `VALID_PATHS = set(PATH_ORDER) | {'seilbahn'}`; `is_subtask_required_for_path()` handles seilbahn isolation; `get_visible_subtasks_for_student()` uses `VALID_PATHS`
- `app.py`: 2 route validators + `_build_topic_preview()` path_counts include seilbahn
- `templates/admin/schueler_detail.html`: 🚡 badge + dropdown option
- `templates/admin/klasse_detail.html`: Seilbahn in class-wide setter
- `templates/admin/aufgabe_detail.html`: Seilbahn in both subtask path dropdowns
- `templates/admin/themen_import.html`: shows `(🚡 N)` for Seilbahn units instead of three-path breakdown
- No migration needed (lernpfad column is free text)

---

## Previous Session (2026-03-01) — DSGVO update + Klarnamen removal plan

**DSGVO documents partially updated** (in progress):
- `docs/vorlagen/informationsschreiben_lernmanager.md` updated

**Plan created** to remove Klarnamen from server:
- Plan file: `~/.claude/plans/composed-greeting-boot.md`
- Deferred — not yet implemented

---

## Next Steps
1. **Commit** the Seilbahn import bugfix
2. **Implement Klarnamen removal** — see plan `~/.claude/plans/composed-greeting-boot.md`
3. **Finish DSGVO docs** — after Klarnamen removal is deployed
4. **Run migrations on server** in order: 006 → 007 → 008
5. **Obtain DPA** from OVHcloud before enabling LLM artifact feedback
6. **Benchmark** Qwen3-32B on Unit 4 rubric for German-language checklist grading

---

## Previous Sessions (summary)

- **2026-03-02**: Seilbahn path support + progress dot numbers
- **2026-03-01**: DSGVO update + Klarnamen removal plan
- **2026-02-25**: Sidequest rename + batch assign + nav favicon
- **2026-02-25**: essay-feedback standalone prototype created
- **2026-02-24**: OVHcloud LLM provider, quiz order fix, LLM logging, quiz feedback cleanup
- **2026-02-24**: Design: artifact feedback + DSGVO analysis (no code)
- **2026-02-24**: Import overwrite bugfix (UNIQUE dedup)
- **2026-02-24**: Task page declutter + font fix
- **2026-02-23**: fertig_wenn field + visual completion zone; UX P0–P7; authoring rules
- **2026-02-23**: db_crypto.py switch; plain SQLite confirmed (SQLCipher removed)
- **2026-02-23**: AJAX quiz dot fix, quiz navigation PRG fix, waitress connection_limit fix
- **2026-02-23**: Production bug fixes (path badge, class lernpfad, duplicate students)
- **2026-02-23**: Learning paths aligned with shared decisions
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
- **Klarnamen removal plan:** `~/.claude/plans/composed-greeting-boot.md`
- **Artifact feedback plan:** `docs/2026-02-24_artifact_feedback_plan.md`
- **DSGVO analysis:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md` (Section 5+6)
- **Informationsschreiben:** `docs/vorlagen/informationsschreiben_lernmanager.md`
- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md`
