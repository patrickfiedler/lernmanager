# Lernmanager - Current State (2026-02-24)

## Latest Session (2026-02-24) — Bug fixes + practice nudge

### What happened

**Import overwrite UNIQUE bug (second fix)**
- First fix (last session) handled duplicate rows for the *same task* — but missed a second case
- New case: student completed Kapitel 2 (abgeschlossen=1), moved to Kapitel 4 (abgeschlossen=0); importing Kapitel 2 without reset tries to reopen it → UNIQUE violation
- Fix 1: `reset_student_progress_for_task()` in `models.py` — UPDATE guard subquery (already existed, now actually covers this case)
- Fix 2: `_recalculate_completion()` in `import_task.py` — added conflict check before setting `abgeschlossen=0`; skips update if student already has another active primary in same class

**Warmup counter bug fix** (`templates/student/warmup.html`)
- "Frage 3 von 2" shown after hard questions added
- Fix: `totalQuestions` variable (starts at `questions.length`, incremented by `data.questions.length` when hard round arrives), used instead of `questions.length` in counter

**Practice session nudge + quiz logging** (migration + 4 files)
- `migrate_008_warmup_session_type.py` — run locally ✓; adds `session_type TEXT DEFAULT 'warmup'` to `warmup_session`
- `models.py`: `save_warmup_session()` now accepts `session_type` param; new `count_practice_sessions_today(student_id)` function
- `app.py`: `student_warmup_finish` passes `session_type` from JSON; `student_practice` passes `practice_sessions_today` to template
- `practice.html`: sends `session_type: 'practice'`; shows info-blue nudge banner when `practice_sessions_today >= 2`
- `warmup.html`: sends `session_type: 'warmup'` in both finish and skip calls

**P4 dot legend** — done (no TODO(human) remaining in klasse.html)

### Git state
- Committed and ready to push
- Pending server migrations: `migrate_006_add_fertig_wenn.py`, `migrate_007_add_tipps.py`, `migrate_008_warmup_session_type.py`

### Next Steps
1. **Push + deploy**: `git push` → ssh server → `sudo /opt/lernmanager/deploy/update.sh`
2. **Run migrations on server** (in order): 006 → 007 → 008
3. **Content reauthoring** — move `💡 Tipp:` content in MBI JSON source files into the new `tipps` field
4. **Graded artifact UI** — `graded_artifact_json` column on `subtask` exists but display not yet implemented

---

## Previous Sessions (summary)

- **2026-02-24**: Import overwrite bugfix (UNIQUE dedup)
- **2026-02-24**: Task page declutter + font fix
- **2026-02-23**: fertig_wenn field + visual completion zone; UX P0–P7; authoring rules
- **2026-02-23**: db_crypto.py switch op; plain SQLite confirmed (SQLCipher removed)
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
