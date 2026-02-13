# Research: Learning Paths & Quiz Evolution (2026-02-07)

## Overview

Three interconnected features researched for the Lernmanager app:
1. Differentiated learning paths (Wanderweg/Bergweg/Gipfelweg)
2. Per-task quizzes (quiz after each Aufgabe, not just per Thema)
3. New question types with LLM-based grading

---

## 1. Learning Paths (Wanderweg / Bergweg / Gipfelweg)

### Concept
Three difficulty paths sourced from the same task pool. Not every task is required for every path. Students can switch paths anytime.

| Path | German | Difficulty | Description |
|------|--------|-----------|-------------|
| Wanderweg | Wanderweg | Basic | Core tasks only |
| Bergweg | Bergweg | Intermediate | Core + challenging tasks |
| Gipfelweg | Gipfelweg | Advanced | All tasks including advanced |

### Current State
- `task.kategorie` has pflicht/bonus — no difficulty level
- `student_task` enforces one active task per student per class (UNIQUE on student_id + klasse_id)
- `subtask_visibility` already supports per-student filtering

### Required Changes

**Database:**
- Add `schwierigkeitsgrad` field to `task` table (wanderweg/bergweg/gipfelweg)
- Add `lernpfad` field to `student` or `student_task` table (chosen path)

**Architecture Option A — Path as Filter (Recommended):**
- All tasks exist in one pool, tagged with difficulty
- Student picks a path → app filters visible tasks
- Switching paths = update one field, visibility adjusts automatically
- Leverages existing `subtask_visibility` pattern
- Simpler, more flexible

**Architecture Option B — Separate Assignments:**
- Three parallel task sequences per class
- More rigid, harder to switch
- Not recommended — contradicts KISS

### Mountain Visualization

Progress visualized as a mountain with three trails:
- Custom SVG or illustrated background in student `klasse.html`
- Each task = a "station" on the trail
- Completed stations → checkmark/flag
- Current task → glow/pulse animation
- Would replace or complement existing progress dots
- Implementation: SVG component + CSS + JS positioning logic
- Effort: Medium (new template section, significant but self-contained)

---

## 2. Per-Task Quizzes

### Current State
- Quizzes stored in `task.quiz_json` — **Thema level only**
- Subtasks (Aufgaben) have no quiz capability
- One quiz per topic, shown after all tasks complete
- Quiz grading: 70% threshold to pass
- Quiz attempts tracked in `quiz_attempt` table

### Required Changes

**Database:**
- Add `quiz_json` column to `subtask` table

**Completion flow:**
- Currently: `check_task_completion()` checks all subtasks + one topic quiz
- New: check each subtask's individual quiz before allowing next subtask
- Topic-level quiz can remain as optional final assessment

**Routes:**
- Modify or add quiz route to handle subtask-level quizzes
- Parameterize: "which quiz_json to load" (topic vs. subtask)

**UI:**
- Show mini-quiz after task completion, before advancing
- Reuse existing quiz rendering/grading logic from `app.py` (~lines 1425-1520)

### Design Decision (Open)
Should subtask quizzes replace or coexist with topic-level quiz?
- Recommendation: coexist — per-task quizzes for reinforcement, topic quiz for summary assessment

---

## 3. New Question Types

### Current Quiz JSON Format
```json
{
  "questions": [
    {
      "text": "Question text",
      "options": ["A", "B", "C", "D"],
      "correct": [0, 2]
    }
  ]
}
```
All questions are implicitly multiple-choice. No `type` field.

### Proposed: Add `type` Field

| Type | JSON Format | Grading | UI | Effort |
|------|------------|---------|-----|--------|
| `multiple_choice` | Current format (default if no type) | Index comparison | Checkboxes (existing) | None |
| `true_false` | 2 options | Same as MC | Toggle UI | Trivial |
| `fill_blank` | `{"type": "fill_blank", "text": "...", "blank": "___", "answers": ["sky", "Sky"]}` | String match or LLM | Text input | Small |
| `short_answer` | `{"type": "short_answer", "text": "...", "rubric": "..."}` | LLM only | Textarea | Small |
| `matching` | `{"type": "matching", "pairs": [["left", "right"], ...]}` | Pair comparison or LLM | Dropdowns / drag-drop | Medium |
| `ordering` | `{"type": "ordering", "items": [...], "correct_order": [2,0,1,3]}` | Array comparison | Drag-drop list | Medium |

### Implementation Priority
1. true/false — already works, just nicer UI
2. fill_blank — small effort, high value
3. short_answer — needs LLM grading
4. matching — medium effort
5. ordering — medium effort

---

## 4. LLM-Based Grading with Claude Haiku

### Architecture
```
Student submits free-text answer
  → Flask route
  → grade_with_llm(question, expected_answer, student_answer)
  → Anthropic API call (Haiku model)
  → Returns: {"correct": bool, "score": 0.0-1.0, "feedback": "..."}
  → Save to quiz_attempt as usual
```

### Cost Estimate
- Haiku: ~$1/M input, $5/M output tokens
- Per grading call: ~230 input + ~80 output tokens = ~$0.0006
- 30 students × 10 questions × 5 topics = 1,500 gradings → **~$0.90/class**

### Privacy / DSGVO
- **Anonymized by design**: only question + expected answer + student answer sent
- No student name, ID, username, class, or school ever included in API calls
- Anthropic API does not train on inputs
- Document in school's Verarbeitungsverzeichnis

### API Key Management
- Add `ANTHROPIC_API_KEY` to `.env` file (same pattern as SECRET_KEY, SQLCIPHER_KEY)
- Loaded via systemd EnvironmentFile, root-owned mode 600
- Add `anthropic` package to `requirements.txt`

### Rate Limiting
- New `api_usage` table with timestamps
- Per student: max 10 grading calls / hour
- Global: monthly budget cap (e.g. 50,000 calls)
- Simple DB-backed counter, no Redis needed

### Fallback When API Down
- Timeout: 3 seconds max
- Fallback: case-insensitive exact string matching
- Student is not blocked from learning if API unreachable

### Prompt Design
```
System: You grade student answers in a German school context.
Respond ONLY with JSON: {"correct": bool, "score": 0.0-1.0, "feedback": "one sentence in German"}
Accept answers that are semantically correct even if spelling/capitalization differs slightly.

User: Question: {question_text}
Expected answer: {expected}
Student answer: {student_answer}
```

---

## Implementation Order (Recommended)

1. **Learning paths data model** — add difficulty field, student path selection
2. **Learning paths UI** — path selector, filtered task display, visual cues
3. **Mountain visualization** — SVG progress view (can be done later)
4. **Per-task quizzes** — quiz_json on subtask table, modified completion flow
5. **New question types** — type field, fill-blank + true/false first
6. **LLM grading** — Haiku integration for free-text answers

Steps 1-2 and 4-5 are somewhat independent and could be worked on in parallel.

---

## Open Questions

- Should learning path be per-student-per-class or a global student preference?
- Should path switching require admin approval or be student-controlled?
- Should the mountain visualization be the primary navigation or a supplementary view?
- Should LLM grading give partial credit (score 0.0-1.0) or just pass/fail?

---

## 5. DSGVO-Analyse: Datenschutz im Lernmanager

### Pseudonymisierung vs. Anonymisierung

| | Pseudonymisiert | Anonymisiert |
|---|---|---|
| Rückführung auf Person möglich? | Ja, mit Zuordnungsdatei | Nein |
| Personenbezogene Daten i.S.d. DSGVO? | **Ja** (Art. 4 Abs. 5) | **Nein** — DSGVO gilt nicht |
| Beispiel | happypanda → Max Müller (via lokale Datei) | happypanda, keine Zuordnung existiert |

### Geplante Architektur

- **App/Server**: Nur Pseudonyme (z.B. happypanda), keine Klarnamen
- **Lehrergerät**: Verschlüsselter Rechner mit Zuordnungsdatei (Pseudonym ↔ Klarname)
- **API-Aufrufe (LLM-Bewertung)**: Vollständig anonym — nur Frage + Antwort, kein Pseudonym, keine Klasse, keine Metadaten
- Zuordnungsdatei wird nur bei Bedarf genutzt (z.B. Zeugniserstellung, Berichte)

### Rechtsgrundlage

**Art. 6 Abs. 1 lit. e DSGVO — Öffentliches Interesse / Bildungsauftrag**

Für schulische Lernplattformen ist die Rechtsgrundlage in der Regel der **öffentliche Bildungsauftrag**, NICHT die Einwilligung der Eltern. Gründe:

- **Einwilligung ist problematisch** in Schulen wegen des Machtgefälles (Erwägungsgrund 43 DSGVO) — Schüler/Eltern können nicht frei ablehnen, wenn die Teilnahme die Note beeinflusst
- **Datenschutzkonferenzen** empfehlen: Schulen sollten sich auf den Bildungsauftrag stützen, nicht auf Einwilligung
- Verarbeitung von Lernfortschritt, Quizergebnissen und Aktivitätsprotokollen ist **Kernaufgabe des Bildungsauftrags**

→ **Schriftliche Einwilligung der Eltern ist in der Regel NICHT erforderlich.**

### Was stattdessen erforderlich ist

1. **Informationspflicht (Art. 13/14 DSGVO)**
   - Eltern/Schüler müssen über die Verarbeitung **informiert** werden (≠ Einwilligung)
   - Formular: Informationsschreiben (kein Unterschriftsfeld nötig)
   - Siehe: `docs/vorlagen/informationsschreiben_lernmanager.md`

2. **Verarbeitungsverzeichnis (Art. 30 DSGVO)**
   - Die Schule führt ein Verzeichnis aller Verarbeitungstätigkeiten
   - Der Lernmanager muss dort eingetragen werden

3. **Genehmigung durch die Schulleitung**
   - Kein DSGVO-Erfordernis, sondern Schulrecht
   - Die meisten Bundesländer verlangen die Genehmigung digitaler Werkzeuge durch die Schulleitung

4. **Auftragsverarbeitungsvertrag (Art. 28 DSGVO)**
   - Mit dem VPS-Hoster (Server-Betreiber) muss ein AV-Vertrag bestehen
   - Für Claude API: Da die Daten vollständig anonymisiert sind (nur Frage + Antwort), gilt die DSGVO nicht für diese Aufrufe

5. **Landesspezifische Regelungen prüfen**
   - Bildungsrecht ist Ländersache — Schuldatenschutzverordnung des eigenen Bundeslandes prüfen
   - Nutzung privater Lehrergeräte für die Zuordnungsdatei kann eine Dienstvereinbarung erfordern

### API-Aufrufe: Anonymisierung

Die LLM-Bewertungsaufrufe sind **funktional anonym**:

```
Gesendet:     "Frage: Hauptstadt von Frankreich? Antwort: Paris"
Nicht gesendet: Schülername, Pseudonym, Klasse, Schule, Zeitstempel
```

- Anthropic kann die Daten keiner Person zuordnen → keine personenbezogenen Daten
- DSGVO gilt nicht für diese Aufrufe (Erwägungsgrund 26)
- Kein AV-Vertrag mit Anthropic erforderlich für anonyme Daten

### Risikobewertung

| Szenario | Risiko | Maßnahme |
|---|---|---|
| Server-Breach | Nur Pseudonyme + Lernfortschritt offengelegt, keine Klarnamen | Verschlüsselung (SQLCipher), Pseudonymisierung |
| Verlust Lehrergerät | Zuordnungsdatei könnte zugänglich sein | Geräteverschlüsselung, starkes Passwort |
| API-Datenleck | Keine personenbezogenen Daten betroffen | Anonymisierung by Design |
| Re-Identifizierung durch Kontext | Lehrkraft in kleiner Klasse könnte Pseudonyme zuordnen | Akzeptables Risiko — Lehrkraft hat ohnehin Zugang |

### Checkliste für den Einsatz

- [ ] Informationsschreiben an Eltern/Schüler verteilen
- [ ] Verarbeitungsverzeichnis der Schule aktualisieren
- [ ] Genehmigung der Schulleitung einholen
- [ ] AV-Vertrag mit VPS-Hoster abschließen
- [ ] Landesspezifische Regelungen prüfen (Schuldatenschutzverordnung)
- [ ] Ggf. Dienstvereinbarung für Nutzung privater Geräte prüfen
- [ ] Datenschutzbeauftragten der Schule informieren
