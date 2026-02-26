# Lernmanager - Current State (2026-02-25)

## Latest Session (2026-02-25) — Sidequest rename + batch assign + nav favicon

### What happened

**Sidequest → "Freiwilliges Thema" rename + batch assign + admin overview** (commit `0e3ad6b`)
- `templates/student/dashboard.html`: badge `⚔️ Sidequest` → `✨ Freiwilliges Thema`
- `models.py`: new `get_sidequests_for_klasse(klasse_id)` — returns active sidequests per student in class
- `app.py`: new route `POST /admin/klasse/<id>/sidequest-zuweisen` + `admin_klasse_detail` passes `sidequests`
- `templates/admin/klasse_detail.html`: batch assign form (topic dropdown + student checkboxes + "Alle wählen") + conditional overview table

**Nav bar favicon** (uncommitted, work in progress)
- Created `static/favicon-light.svg` — same as `favicon.svg` but frame/stand changed from blue `#3b82f6` → off-white `#cbd5e1` (slate-300) so it's visible on the blue nav background
- `templates/base.html`: logo link now uses `favicon-light.svg` instead of `📚` emoji
- Still needs a commit

### Git state
- Last committed: `0e3ad6b`
- **Uncommitted changes**: `static/favicon-light.svg` (new file), `templates/base.html` (favicon in nav)
- **Pending server migrations still unrun**: `migrate_006` → `migrate_007` → `migrate_008`

### Next Steps
1. **Commit** favicon-light + base.html changes
2. **Run migrations on server** in order: 006 → 007 → 008 (then deploy latest code)
3. **Obtain DPA** from OVHcloud before enabling LLM artifact feedback
4. **Benchmark** Qwen3-32B on Unit 4 rubric for German-language checklist grading
5. **Continue content reauthoring** — Units 2 + 4

---

## Previous Session (2026-02-25) — essay-feedback prototype created

**New standalone prototype: `/home/patrick/coding/essay-feedback/`**
- Minimal Flask app (no login, no DB) for students to type essay responses and get Claude Haiku feedback
- Secret URL pattern: `/e/<SECRET_TOKEN>` — token set via env var
- **TODO(human) in `app.py`**: `SYSTEM_PROMPT` is empty — teacher must write the German prompt

---

## Previous Sessions (summary)

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
- **Artifact feedback plan:** `docs/2026-02-24_artifact_feedback_plan.md`
- **DSGVO analysis:** `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md` (Section 5+6)
- **Pedagogical rationale:** `docs/pedagogy/pedagogical_decisions.md`
