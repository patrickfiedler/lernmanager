# Lernmanager - Current State (2026-03-02)

## Latest Session (2026-03-02b) — Seilbahn path support

**Seilbahn added as fourth, non-cumulative learning path** (commit pending):
- `models.py`: `VALID_PATHS = set(PATH_ORDER) | {'seilbahn'}`; `is_subtask_required_for_path()` handles seilbahn isolation; `get_visible_subtasks_for_student()` uses `VALID_PATHS`
- `app.py`: 2 route validators + `_build_topic_preview()` path_counts include seilbahn
- `templates/admin/schueler_detail.html`: 🚡 badge + dropdown option
- `templates/admin/klasse_detail.html`: Seilbahn in class-wide setter
- `templates/admin/aufgabe_detail.html`: Seilbahn in both subtask path dropdowns
- `templates/admin/themen_import.html`: shows `(🚡 N)` for Seilbahn units instead of three-path breakdown
- No migration needed (lernpfad column is free text)

### Git state
- Uncommitted: `docs/vorlagen/informationsschreiben_lernmanager.md` (partial DSGVO update — separate task)
- Pending server migrations still unrun: `migrate_006` → `migrate_007` → `migrate_008`

## Previous Session (2026-03-02a) — Progress dot numbers

**Small UI fix committed**: Task numbers now appear inside progress dots (`c3163c1`).
- `templates/student/klasse.html`: `<span class="dot-num">{{ loop.index }}</span>` inside each `.dot-subtask`
- `static/css/style.css`: `.dot` gains flex centering; `.dot-num` styles (0.6rem, white 85% opacity); counter-rotate for optional/diamond dots

---

## Previous Session (2026-03-01) — DSGVO update + Klarnamen removal plan

**DSGVO documents partially updated** (in progress):
- `docs/vorlagen/informationsschreiben_lernmanager.md` updated:
  - Section 4: Added "Übungshistorie" and "Lernpfad"; "Lernzielkontrollen" → "Übungsquizzes (nicht benotet)"
  - Section 5: LLM provider updated to OVHcloud (EU, France)
  - Section 6: SQLCipher reference removed; hoster = Strato AG (Germany/EU)
  - Section 7: Anthropic → OVHcloud in recipients table

**Key finding**: `vorname` and `nachname` stored in `student` table — contradicts "Klarnamen nicht auf Server" claim.

**Plan created** to remove Klarnamen from server:
- Plan file: `~/.claude/plans/composed-greeting-boot.md`
- Deferred — not yet implemented

**What the plan covers:**
1. `migrate_009_remove_real_names.py` — drop vorname/nachname from student table
2. `models.py` — remove name columns from schema + 7 model functions
3. `app.py` — session key rename, flash messages, batch creation, PDF filenames
4. 5 admin templates + `base.html` + `dashboard.html` → show username instead of names
5. `utils.py` — PDF report headers; `anonymize_db.py` — remove fake_name()
6. DSGVO docs — finalize after code change

**DSGVO doc still needs** (once Klarnamen removal is implemented):
- Update Section 4 "Klarnamen nicht auf Server" → becomes factually true
- Update research doc risk table: `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md` line 271

---

## Next Steps
1. **Implement Klarnamen removal** — see plan `~/.claude/plans/composed-greeting-boot.md`
2. **Finish DSGVO docs** — after Klarnamen removal is deployed
3. **Run migrations on server** in order: 006 → 007 → 008
4. **Obtain DPA** from OVHcloud before enabling LLM artifact feedback
5. **Benchmark** Qwen3-32B on Unit 4 rubric for German-language checklist grading

---

## Previous Sessions (summary)

- **2026-03-02**: Progress dot numbers (small UI fix)
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
