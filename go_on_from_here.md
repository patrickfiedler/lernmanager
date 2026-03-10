# Lernmanager - Current State (2026-03-10, Session 5)

## This Session — DSGVO & Pädagogik go-public prep

### DSGVO / Privacy
- `deploy/nginx.conf`: `access_log off` added (IP addresses no longer logged; error log kept)
- `app.py`: public `/datenschutz` route added (no login required)
- `templates/datenschutz.html`: full Datenschutzerklärung created (Art. 13 DSGVO)
- `templates/base.html`: footer with Datenschutzerklärung link added to every page
- Language fixes across both Datenschutzerklärung and Informationsschreiben:
  - "Prüfergebnis" → "Vollständigkeitsrückmeldung (Checkliste: Ja/Nein pro Kriterium)"
  - "Warmup / Spaced Repetition" → "Aufwärm-Quiz und Wiederholungsübungen (verteiltes Üben)"
  - "Wiederholungsdurchlauf" → "Aufwärm-Quiz" in Elternbrief
  - Retention period: "am Ende des Schuljahres" → "zuzüglich zwei Monate"
- `docs/vorlagen/informationsschreiben_lernmanager.md`: synced all above changes
- `docs/vorlagen/elternbrief_lernmanager.md`: Aufwärm-Quiz fix + pedagogical context paragraph added

### Pädagogik
- `docs/pedagogy/schulkonzept_lernmanager.md`: new — school-facing pedagogical concept (Montessori, Formative Assessment, Vygotsky, Ebbinghaus, Binnendifferenzierung)
- `docs/vorlagen/elternbrief_paedagogisches_konzept.md`: new — parent-facing pedagogical concept letter
- Montessori analysis: documented in session (not written to file — request if needed)

### todo.md updates
- New "DSGVO (Go-Public)" section with: nginx done, Datenschutzerklärung done, placeholders still needed, retention policy spec, deletion/export plan, Elternbrief finalisieren

---

## Still To Do

1. **Deploy** (BLOCKER): run `migrate_009_artifact_feedback.py` on server → then `update.sh`
2. **Datenschutzerklärung placeholders**: fill school name, DSB contact, Schulgesetz reference before going live
3. **Elternbrief finalisieren**: fill placeholders in `docs/vorlagen/elternbrief_lernmanager.md` and `elternbrief_paedagogisches_konzept.md`
4. **DSB der Schule informieren** before parent communication
5. **DSGVO steps** before enabling artifact feedback for any class (see `docs/2026-02-24_artifact_feedback_plan.md`)
6. **Benchmark**: GPT-OSS 120B vs Qwen3-32B on Unit 4 rubric
7. **Other units**: add `criteria` arrays to catchup_B, kapitel_01, kapitel_02

---

## Key References

- **Architecture & conventions:** `CLAUDE.md`
- **Open tasks:** `todo.md`
- **Datenschutzerklärung:** `templates/datenschutz.html` + `docs/vorlagen/informationsschreiben_lernmanager.md`
- **Elternbriefe:** `docs/vorlagen/elternbrief_lernmanager.md`, `docs/vorlagen/elternbrief_paedagogisches_konzept.md`
- **Pädagogisches Konzept (Schule):** `docs/pedagogy/schulkonzept_lernmanager.md`
- **Artifact feedback design:** `docs/2026-02-24_artifact_feedback_plan.md`
