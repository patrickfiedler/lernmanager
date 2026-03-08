# Artifact Feedback & Step Checkboxes — Design Plan

**Status:** Decisions confirmed 2026-03-04
**Date:** 2026-02-24 | **Updated:** 2026-03-04
**Origin:** Design discussion session + implementation discussion

## Confirmed Decisions (2026-03-04)

| # | Decision |
|---|---|
| 0 | Copy & adapt relevant parts from grading-with-llm into new `artifact_processor.py` (~200 lines). No shared dependency — divergence risk is acceptable for stable extraction code. |
| 1 | Rubric source: structured `criteria` array in `graded_artifact_json`. Not fertig_wenn prose (too informal for reliable LLM grading). |
| 2 | Store feedback result (✓/✗ + one sentence per criterion + `timestamp_local` + `timezone`) in `artifact_feedback` table. Original file and extracted text never touch disk. |
| 3 | File format priority: `.pptx`/`.odp` first (Unit 4 uses these), `.sb3` second, `.docx`/`.odt` third. |
| 4 | Opt-in: teacher enables per-class toggle. Parents informed via Art. 13 (Informationsschreiben). Objections via Art. 21 Widerspruchsrecht — teacher disables per student in admin. No consent stored in DB. |
| 5 | LLM backend: benchmark IONOS GPT-OSS 120B (🇩🇪, ~€0.14/mo), IONOS Mistral Small 24B (🇩🇪, ~€0.08/mo), OVHcloud Qwen3-32B (🇫🇷, ~€0.06/mo) on a Unit 4 rubric. IONOS preferred for German school sovereignty. AWS Bedrock EU only as last resort (CLOUD Act risk). |

**Implementation plan:** `~/.claude/plans/artifact-feedback-impl.md`

---

## Problem

Students are overwhelmed by wall-of-text task descriptions (10–25 lines). They also get no quality feedback on their growing artifact until the teacher manually grades the capstone — by which point errors have compounded across multiple tasks.

## Design Decisions Made

### 1. Per-step checkboxes (process tracking)

Numbered steps inside `📋 Aufgabe:` get checkboxes. Students tick off steps as they work.

- All steps remain visible (not progressive disclosure — students need to skim and refer back)
- State persisted in DB (school computers clear localStorage)
- Purely for student self-tracking — not logged to teacher, not grading-relevant
- Orthogonal to artifact grading

**Open:** new DB table needed for step-completion state (per student, per subtask, per step index)

### 2. Per-task artifact upload with formative LLM feedback

After completing the steps of any task that produces artifact output, students can upload their file. The LLM checks it against a task-scoped rubric and returns checklist-style feedback.

- Upload is **optional at every stage** — no gating, no blocking
- Feedback is **formative only** — no numeric score shown to students
- Format: ✓/✗ per observable criterion + short explanation
- Students can re-upload after fixing issues
- The rubric **grows organically** — task N rubric = task N-1 criteria + new criteria for task N

### 3. Teacher sets the final grade

The teacher manually reviews the capstone submission and enters the grade. The LLM is a tool, not an authority. The grade number comes only from the teacher.

| Layer | What it does | Binding? |
|-------|-------------|---------|
| Per-step checkboxes | Student tracks own process through a task | No |
| Per-task artifact upload | LLM checks criteria for tasks done so far | No — formative |
| Capstone upload | LLM checks all unit criteria | No — teacher reviews |
| Teacher grade entry | Sets the actual grade in the system | Yes |

---

## Two Grading Flows

These are distinct, complementary, and serve different purposes.

### Flow A — In-app, student-initiated (formative)

Student uploads during or after a task → text extracted + pseudonymized → preview shown → (if LLM feedback enabled) LLM checks against growing rubric → checklist feedback shown → student can fix and re-upload.

- No batching. Triggered on upload.
- Student is already authenticated — filename is irrelevant for identity. It's just a criterion to check.
- Runs via extended `llm_grading.py`, standard Anthropic API (no batch discount).
- **LLM feedback is opt-in per class** (see Privacy section). Upload + preview always work regardless.

### Flow B — Teacher-initiated batch (summative)

Teacher runs PowerShell file collection → grading-with-llm CLI on teacher's machine → results pushed to Lernmanager API → teacher reviews → sets grade.

- grading-with-llm runs unchanged. No Lernmanager server involvement.
- Uses Batch API (50% cost discount, async).
- Natural trigger: end of unit, not per-task.

### Why not batch-only?

Self-paced students finish tasks at different times — there's never a natural class-wide collection moment. For 10-12 year olds, feedback arriving next lesson is pedagogically weak: emotional connection to the work is gone, motivation to revise drops sharply. Flow A closes the per-task loop immediately; Flow B handles the final summative grade at the teacher's discretion.

---

## File Management

Students in grades 5/6 are just learning file handling. The concern is that early uploads will be messy (wrong filename, wrong format, wrong file entirely).

**This is not a blocker — it's a learning mechanism.** The filename is already a `fertig_wenn` criterion ("Deine Datei heißt genau `Digitaler-Kompass-[Vorname].pptx`"). When the student uploads the wrong filename, they see it immediately in the preview — before any API call. The first few failed checks teach file discipline at low stakes.

For Flow B identity is resolved by filename (network login: `mueller.anna.pptx`) — this is the existing grading-with-llm convention and is unchanged.

**Files are not stored on the Lernmanager server.** The uploaded file is processed in memory: metadata stripped, text extracted, student name pseudonymized. Only the extracted text and feedback result are stored (in `artifact_feedback` table). The original file is discarded after extraction. For Flow B, the teacher collects files directly from network folders — Lernmanager is not a file store.

---

## Privacy & DSGVO

### Two distinct processing activities

| Activity | Data stays | Legal basis | Status |
|----------|-----------|-------------|--------|
| Upload + extract + preview | Lernmanager server only | Art. 6 lit. e (Bildungsauftrag) | Always available |
| Send to Anthropic API | Leaves school infrastructure | Needs clarification | **Opt-in per class** |

Keeping these separate means the feature can ship and be used without resolving the API question first.

### Pseudonymization before any API call

Adapted from grading-with-llm's anonymization layer:

1. **Strip document metadata** — `.pptx` author/creator fields removed via `python-pptx` before any storage
2. **Replace student name in text** — first name, last name, and combinations replaced with `[Schüler/in]` before API call. Student identity is already known from the session; pseudonym is only for the API payload.
3. **No original file stored** — only extracted + cleaned text stored server-side

### Student preview (transparency)

Before any API call, the student sees the extracted + pseudonymized text in a collapsible section:

> *"Das sieht die KI: [extracted text with name replaced]. Dein Name und persönliche Daten wurden ersetzt."*

This serves both DSGVO transparency and pedagogy — Unit 4 is literally about data privacy. Seeing this in action is a teaching moment.

### Opt-in: teacher enables LLM feedback per class (Decision 4)

Admin setting per Klasse: "KI-Aufgabencheck aktiviert" (off by default). Stored as column on `klasse` table.

- When off: upload + preview work, no API call made, no feedback shown
- When on: full Flow A with checklist feedback
- Teacher enables after DSGVO prerequisites are met (see below)

**No per-student consent stored in DB.** Legal basis is Art. 6(1)(e) — parental consent (Einwilligung) is not the correct mechanism and would create a *Scheineinwilligung*. Parents are informed via Art. 13 Informationsschreiben. If a parent objects (Art. 21 Widerspruchsrecht), the teacher disables the feature for that student via the existing admin student detail page.

### Legal basis analysis

**Art. 6 lit. f (berechtigtes Interesse) — not available.** Public schools are public authorities; lit. f explicitly excludes them. Common misconception.

**Art. 6 lit. e (öffentliche Aufgabe) — correct basis, with conditions.** School education is a public task. ThürSchulG §70 authorises data processing for educational purposes. Parental consent (Einwilligung) is therefore NOT required as the primary legal basis for routine educational processing. What parents are owed is transparency (Art. 13 DSGVO notification), not consent.

However, "necessary" is a real constraint. German DSBs interpret it strictly. A local alternative that achieves the same purpose weakens the "necessary" argument for cloud API specifically — see Ollama note below.

**The harder problem: Chapter V (international transfers).** Anthropic is a US company. Even if Art. 6 lit. e covers the purpose, the transfer to a non-EU country needs a separate basis:
- **EU-US Data Privacy Framework (DPF):** valid if Anthropic is certified — needs verification
- **Standard Contractual Clauses (SCCs):** likely included in Anthropic's DPA as fallback

German DSBs have been consistently strict on US cloud services in schools. Several states have restricted Google Workspace and Microsoft 365 for exactly this reason. Thuringia's DSB may have specific school cloud guidance — check before enabling.

### What must be done before enabling the feature

| Step | What | Status |
|------|------|--------|
| DPA (Art. 28 AVV) | Contract with Anthropic as Auftragsverarbeiter | Not done — Anthropic provides one |
| Transfer basis | Verify Anthropic DPF certification or confirm SCCs in DPA | Needs verification |
| Confirm no training use | Anthropic API must not use inputs for model training — verify in DPA | Needs verification |
| DPIA (Art. 35) | Likely required for systematic LLM processing of minor's work | Needs DSB input |
| ThürDSB guidance | Thuringia may have specific school cloud service rules | Check |
| School privacy notice | Add LLM processing to Datenschutzerklärung (Art. 13 obligation) | Required |
| DSB / Schulleitung sign-off | School's own data protection officer should approve | Required |

**Nothing above is optional. The feature must not be enabled for any class until all steps are complete.**

### Why Ollama is not a practical alternative

grading-with-llm supports Ollama (local LLM, school-controlled infrastructure) which would avoid the Chapter V transfer problem entirely. However:
- Accuracy: 93.2% vs. 98.3% for Haiku 4.5 on the same task
- Speed: matching Haiku's throughput (~10 students in 1.2 min) requires significant GPU hardware (7B model minimum, 14B for better accuracy) — far beyond a school VPS budget
- Maintenance: running a local LLM server adds operational complexity

Ollama is a useful fallback for development and testing, not a production substitute at this scale. The DSGVO problem must be solved for the cloud API — not worked around with an underpowered local alternative.

Note: Unit 4 ("Digitaler Kompass") involves students' personal internet habits and privacy opinions — the most sensitive content in the curriculum. Extra care warranted specifically for this unit.

---

## Datenschutz & DSGVO — Rechtliche Analyse

> Vollständige Analyse auch in `docs/research/2026-02-07_learning_paths_and_quiz_evolution.md` Abschnitt 6.

### Warum das Artefakt-Feedback rechtlich anders ist als die Quiz-Bewertung

Die bestehende LLM-Quizbewertung fällt **nicht unter die DSGVO**: Es werden nur anonyme Daten gesendet (Frage + kurze Antwort, kein Identifier). Das Artefakt-Feedback ist anders — vollständige Dokumente können persönliche Inhalte und den Namen des Schülers enthalten. Die DSGVO gilt hier wahrscheinlich.

### Rechtsgrundlage

**Art. 6 lit. f (berechtigtes Interesse) — nicht anwendbar.** Öffentliche Schulen sind Behörden; lit. f gilt ausdrücklich nicht für Behörden bei der Aufgabenerfüllung. Häufiger Irrtum.

**Art. 6 lit. e (öffentliche Aufgabe / Bildungsauftrag) — korrekte Grundlage.** Schulische Bildung ist eine öffentliche Aufgabe. ThürSchulG §70 erlaubt Datenverarbeitung für Bildungszwecke. **Elterneinwilligung ist nicht erforderlich** — und wäre als Grundlage schlechter (widerrufbar, Machtgefälle in der Schule). Eltern haben stattdessen ein Recht auf Information (Art. 13), nicht auf Zustimmung.

### EU-Anbieter vs. US-Anbieter

Die DSGVO unterscheidet zwischen der *Rechtsgrundlage der Verarbeitung* (Art. 6) und dem *Ort der Verarbeitung* (Kapitel V). Beides muss stimmen.

**Bei US-Anbietern (Anthropic)** greift Kapitel V: Jede Übermittlung personenbezogener Daten in ein Drittland braucht eine eigene Grundlage (DPF-Zertifizierung oder SCC). Zusätzlich gilt der **CLOUD Act**: US-Behörden können US-Unternehmen zur Herausgabe von Daten verpflichten — auch wenn diese auf EU-Servern liegen. Das gilt ebenso für AWS EU, Azure EU und Google Cloud EU.

**Bei EU-Anbietern (Mistral, OVHcloud)** entfällt Kapitel V vollständig — eine Übermittlung von Deutschland nach Frankreich ist keine Drittlandübermittlung. Der CLOUD Act gilt nicht.

| Pflicht | US-Anbieter (Anthropic) | EU-Anbieter (Mistral / OVHcloud) |
|--------|------------------------|----------------------------------|
| Art. 6 lit. e Rechtsgrundlage | ✓ erforderlich | ✓ erforderlich |
| AV-Vertrag (Art. 28) | ✓ erforderlich | ✓ erforderlich |
| Kapitel V (Drittlandübermittlung) | ✓ DPF / SCC prüfen | **entfällt** |
| CLOUD Act Risiko | ✓ vorhanden | **entfällt** |
| DPIA (Art. 35) | wahrscheinlich erforderlich | wahrscheinlich nicht nötig |
| Informationspflicht (Art. 13) | ✓ erforderlich | ✓ erforderlich |
| Verarbeitungsverzeichnis (Art. 30) | ✓ erforderlich | ✓ erforderlich |
| DSB / Schulleitung | ✓ empfohlen | ✓ empfohlen |

### Was vor der Aktivierung für eine Klasse erledigt sein muss

**Bei EU-Anbieter (IONOS oder OVHcloud — empfohlen):**
- [ ] AV-Vertrag (Art. 28) mit gewähltem Anbieter abschließen (IONOS und OVHcloud stellen ihn bereit)
- [ ] Keine Modelltrainierung mit API-Eingaben — im AV-Vertrag bestätigen (IONOS: explizit bestätigt in Docs)
- [ ] Informationsschreiben Eltern aktualisieren (Art. 13 Transparenzpflicht)
- [ ] Verarbeitungsverzeichnis aktualisieren (Art. 30)
- [ ] DSB kurz informieren — DPIA wahrscheinlich nicht erforderlich
- [ ] Genehmigung Schulleitung

**Zusätzlich bei AWS Bedrock EU (nur als letzter Ausweg):**
- [ ] AWS DPA (Art. 28 AVV) abschließen
- [ ] CLOUD Act-Risiko dokumentieren und DSB-Freigabe einholen
- [ ] DPIA (Art. 35) wahrscheinlich erforderlich
- [ ] Thüringer DSB-Leitlinien zu US-Schul-Cloud-Diensten prüfen

**Kein Consent von Eltern nötig** — Rechtsgrundlage ist Art. 6 lit. e (Bildungsauftrag). Eltern haben Widerspruchsrecht (Art. 21); Lehrkraft deaktiviert Feature für betreffende Schüler im Admin.

**Das Feature darf für keine Klasse aktiviert werden, bevor diese Schritte abgeschlossen sind.**

### Hinweis zu Einheit 4

„Digitaler Kompass" enthält Schülerreflexionen zu eigenen Online-Erfahrungen und Datenschutzgewohnheiten — inhaltlich das Sensibelste im Curriculum. Gleichzeitig ist die Vorschau des pseudonymisierten Textes vor dem API-Aufruf ein direktes Unterrichtsbeispiel für das Thema Datenschutz.

---

## LLM Backend Options

Two backends are supported. The choice determines DSGVO complexity.

Cost estimates below assume 70 students × 2 uploads/week, ~1000 input + ~150 output tokens per student (560 requests/month).

Cost estimate: 70 students × 2 uploads/week, ~1000 input + 150 output tokens, 560 requests/month.

| Provider | Country | CLOUD Act | Model | Size | Input €/MTok | Output €/MTok | Est. €/month |
|----------|---------|-----------|-------|------|-------------|--------------|-------------|
| **IONOS** | 🇩🇪 DE | None | GPT-OSS 120B | 120B | €0.15 | €0.65 | ~€0.14 |
| **IONOS** | 🇩🇪 DE | None | Mistral Small 24B | 24B | €0.10 | €0.30 | ~€0.08 |
| **OVHcloud** | 🇫🇷 FR | None | Qwen3-32B | 32B | €0.08 | €0.23 | ~€0.06 |
| IONOS | 🇩🇪 DE | None | Llama 3.3 70B | 70B | €0.65 | €0.65 | ~€0.42 |
| AWS Bedrock EU | 🇺🇸 US | Yes | Claude Haiku 4.5 | — | ~€0.72 | ~€3.60 | ~€1.20 |
| Anthropic direct | 🇺🇸 US | Yes | Claude Haiku 4.5 | — | $0.80 | $4.00 | ~€1.20 |
| Mac Mini + WireGuard | local | None | Qwen2.5-14B | 14B | €599 one-time | — | ~€10 amort. |

At this scale, cost differences are negligible (cents/month). Decision is quality and legal sovereignty.

### Option A: IONOS AI Model Hub (Berlin, Germany) — **benchmark candidate 1** (Decision 5)

- **German company, Berlin data center** — strongest legal position for German schools. No CLOUD Act risk.
- **Stateless**: prompts and outputs discarded at session end (confirmed in docs)
- Data not used for training — confirmed
- ISO 27001 certified, DPA (Art. 28 AVV) available
- **GPT-OSS 120B**: €0.15/€0.65 per MTok → ~€0.14/month — large model, good reasoning
- **Mistral Small 24B**: €0.10/€0.30 per MTok → ~€0.08/month — explicitly European multilingual
- **Teuken 7B**: German-specific model (OpenGPT-X), likely weaker on structured tasks but worth noting
- DSGVO process: DPA + Art. 13 notice + DSB sign-off. No DPIA likely needed.
- API: OpenAI-compatible endpoint

### Option B: OVHcloud AI Endpoints (Roubaix, France) — **benchmark candidate 2** (Decision 5)

- French company, 100% EU infrastructure, no US dependencies, ISO 27001
- **Qwen3-32B: €0.08/€0.23 per MTok → ~€0.06/month** — 32B reasoning model, cheapest option
- Qwen3 reasoning mode (extended thinking) may help for structured checklist grading
- DSGVO process: DPA + Art. 13 notice + DSB sign-off, no DPIA likely needed
- Already in use for quiz LLM grading — no new integration work needed

**Benchmark required:** Compare IONOS GPT-OSS 120B, IONOS Mistral Small 24B, and OVHcloud Qwen3-32B on a Unit 4 rubric (German-language checklist) before committing to a provider.

### Option C: Ollama on teacher's Mac Mini via WireGuard

Ollama runs on teacher's home Mac Mini. Production server reaches it via WireGuard tunnel.

**DSGVO situation:** The Mac Mini is teacher's own device — legally equivalent to the teacher's laptop. Pseudonymized artifact text flowing over an encrypted WireGuard tunnel to the home machine and back is no different from downloading a CSV of grades. No third-party processor → no Art. 28 AV-Vertrag for the LLM component. Chapter V international transfer problem disappears entirely. Disk encryption + strong password on Mac Mini required (same as existing Lehrergerät mitigations).

**Performance on Apple Silicon** — significantly better than grading-with-llm's 93.2% CPU benchmark:

| Hardware | Model | Speed | Notes |
|----------|-------|-------|-------|
| School VPS (CPU) | qwen2.5:7b | slow | What grading-with-llm benchmarked |
| M4 Mac Mini (16GB) | 14B 4-bit | ~15 tok/s | Fast enough for real-time use |
| M4 Pro Mac Mini (24GB+) | 32B 4-bit | ~10 tok/s | Near-cloud accuracy territory |

For grading (short prompts, short outputs), 15 tok/s is sufficient. Accuracy gap vs. Haiku narrows with larger models on Apple Silicon — benchmark with actual Unit 4 rubric before committing to a model.

**WireGuard + dynamic home IP:** Mac Mini initiates the tunnel outbound to the VPS (static IP). VPS never needs to reach the home IP directly. Standard setup, well-documented.

**Operational dependency:** Mac Mini must be on and tunnel active during class for Flow A (per-task formative). Flow B (batch capstone) is teacher-initiated — turn it on when needed. If Mac Mini is unreachable, artifact feedback shows "zurzeit nicht verfügbar, später nochmal versuchen" — no silent failure.

**Cost note:** Mac Mini M4 base ~€700. Anthropic API ~€1.20/month → financial break-even is never. The value is avoiding months of DSGVO bureaucracy (DPA, DPIA, DSB consultation, school approval), not cost savings.

**Code changes for Option B:**
- `config.py`: add `LLM_ARTIFACT_ENDPOINT` (WireGuard IP of Mac Mini, e.g. `http://10.0.0.2:11434`)
- Artifact grading module: use Ollama client when endpoint configured, Anthropic when not
- Graceful offline message when Mac Mini unreachable
- Pattern already exists in `llm_grading.py` — Ollama support is not new

**Hardware recommendation: Mac Mini M4 base (16GB, €599)**

Apple Silicon unified memory — unlike traditional PCs, all 16GB is shared between CPU, GPU, and Neural Engine. The full pool is available for the model.

| Model | Memory (Q4) | Fits in 16GB? | Notes |
|-------|------------|--------------|-------|
| Qwen2.5:7B | ~4.5 GB | ✓ comfortably | Good, possibly sufficient |
| Qwen2.5:14B | ~8.5 GB | ✓ well | Recommended target |
| 32B | ~20 GB | ✗ | Needs 24GB M4 Pro |

macOS uses ~3–5 GB, leaving 11–13 GB for model + context. 14B fits cleanly. Context per grading call is small (rubric ~500 tokens + document ~500–1500 tokens + output ~150 tokens) — KV cache overhead is minimal.

Speed on M4 (Metal GPU acceleration): ~25–40 tok/s for 14B. A single student submission with all criteria in one call: ~5–10 seconds — acceptable for Flow A (student waits). For Flow A, one combined checklist call is preferred over 6 sequential micro-prompts; slight accuracy trade-off but appropriate for formative feedback.

M4 Pro (24GB, ~€1,399) would open 32B models but is not justified for this use case. 14B on 16GB gives sufficient quality, good speed, and clean DSGVO at less than half the price.

**Open:** benchmark accuracy of Qwen2.5:14B on Unit 4 rubric before committing.

---

## Code Reuse: grading-with-llm

**Copy & adapt into `artifact_processor.py` — no shared dependency.** (Decision 0)

Rationale: Lernmanager's use case (one student, one file, formative checklist, real-time) is fundamentally simpler than grading-with-llm (batch CLI, CSV output, divide-and-conquer, StudentIDMapper). The full modules are 600–970 lines; the needed surface is ~200 lines. File extraction code is stable — divergence risk is low.

| Component | Approach | Adapted size |
|-----------|----------|-------------|
| `docx_processor.py` (668 lines) | Extract text + tables only; drop images, metadata, full-structure mode | ~80 lines |
| `odt_processor.py` (637 lines) | Same | ~80 lines |
| `anonymizer.py` (370 lines) | Single function: replace student name → `[Schüler/in]` | ~15 lines |
| `prompt_builder.py` + `micro_grader.py` | Not copied — `llm_grading.py` extended with checklist prompt style | 0 lines |
| Batch API + CLI workflow | Flow B only — grading-with-llm runs as-is on teacher's machine | — |

## Supported File Formats

Priority order (Decision 3): `.pptx`/`.odp` first (Unit 4 uses these), `.sb3` second, `.docx`/`.odt` third.

| Format | Library | What's extracted | Priority |
|--------|---------|-----------------|---------|
| `.pptx` | `python-pptx` | Slide text per slide | **Phase 1** |
| `.odp` | `python-pptx` or unzip+XML | Slide text per slide | **Phase 1** |
| `.sb3` | `zipfile` + `json` | Block graph → readable summary | **Phase 2** |
| `.docx` | `python-docx` | Paragraphs + tables | Phase 3 |
| `.odt` | `odfpy` | Paragraphs + tables | Phase 3 |

### .sb3 (Scratch 3 project files)

`.sb3` is a ZIP archive. Inside:
- `project.json` — full project: sprites, script block trees, variables, comments, costume names
- Asset files (costume images, sounds) — binary, ignored for text grading

The Scratch 3 spec is fully open. The challenge: `project.json` stores scripts as a flat dictionary of blocks with opaque IDs (`"next": "abc123"`). Raw JSON sent to an LLM is unreadable noise. A **transformation layer** is needed to convert the block graph into a human-readable summary:

```
Sprite "Katze":
  Skript 1: Wenn [Flagge] → wiederhole 10 mal → bewege 10 Schritte
  Skript 2: Wenn [Leertaste] → sage "Hallo" 2 Sekunden
  Kostüme: katze1, katze2
Variablen: Punkte
Bühne: 1 Hintergrund
```

For grades 5/6, rubric criteria are structural and checkable from such a summary:
- "Has at least 2 sprites" ✓
- "Has a loop block (repeat/forever)" ✓
- "Has a conditional (if/else)" ✓
- "Uses at least one variable" ✓
- "Has comments" ✓

**Assessment:** feasible, but the block-graph-to-summary transformer is ~1–2 days of engineering work. Worth doing — Scratch projects appear in multiple units. Not needed for the first implementation (Unit 4 uses .pptx/.odp).

**Open:** should `.sb3` support be built as a standalone module shareable with grading-with-llm?

---

## Cost Estimate — Unit 4 "Digitaler Kompass"

**Baseline (measured):** grading-with-llm reports ~$0.007 per 10 students per run (Haiku 4.5, Batch API, text-only, 6 criteria, similar rubric complexity).

| Flow | Mode | Per student | 70 students × 1 run | 70 students × 2 runs/week |
|------|------|------------|---------------------|---------------------------|
| Flow B (batch) | Batch API (50% off) | ~$0.0007 | ~$0.05 | ~$0.10/week |
| Flow A (real-time) | Standard API | ~$0.0014 | ~$0.10 | ~$0.20/week |
| **Combined** | | | | **~$0.30/week** |

**Monthly: ~$1.20.** Essentially noise even at 5× overestimate.

Notes:
- `.pptx` slides are intentionally sparse — likely *fewer* tokens than a `.docx` baseline
- Unit 4's qualitative criteria (e.g. "Erklärungen verständlich") need richer prompts than quantitative ones — partially offsets sparse text
- Prompt caching (rubric is repeated per student) would reduce Flow A costs further

---

## Rubric Format (Proposed)

Replace the current 1–4 scoring rubric with a checklist format for per-task feedback:

```json
{
  "graded_artifact": {
    "keyword": "computer-steckbrief",
    "format": [".docx", ".odt"],
    "criteria": [
      "Datei heißt genau 'Steckbrief-[Vorname].docx'",
      "Überschrift 'Mein Computer-Steckbrief' vorhanden und als Überschrift 1 formatiert",
      "Abschnitt 'Hardware' enthält mindestens 3 Komponenten mit je einer Erklärung"
    ]
  }
}
```

LLM prompt instructs: for each criterion, return ✓ or ✗ plus one short sentence of specific feedback. No overall score.

**Open:** define exact prompt structure and output format. Align with `grading-with-llm/conventions.md`.

---

## Growing Rubric Pattern (Authoring Convention)

Each task's `graded_artifact` criteria block = previous task's criteria + new criteria for this task.

Task 1 criteria: [file setup, heading]
Task 2 criteria: [file setup, heading, hardware section]
Task 3 criteria: [file setup, heading, hardware section, software section]
...
Capstone criteria: [everything]

Authoring rule: copy previous task's criteria block, append new criteria for current task. Never remove criteria from a previous task's block. This ensures the LLM always evaluates the full artifact state against what's been taught so far.

**Open:** should this be enforced/checked by `scripts/content_checker.py`?

---

## Implementation Work

1. **Per-step checkboxes**
   - JS: detect numbered `<li>` elements inside the `📋 Aufgabe:` section, inject checkboxes
   - DB: new table for step completion state (student_id, subtask_id, step_index, checked)
   - Minimal — no authoring changes, works on existing content immediately

2. **Upload UI per task**
   - File input widget on task page, shown after checkboxes (or always visible for tasks with `graded_artifact`)
   - Accepts formats listed in `graded_artifact.format`
   - Triggers LLM check on upload, displays checklist result inline

3. **LLM feedback call**
   - Extend `llm_grading.py` with new prompt style (checklist, not score)
   - Store result in new `artifact_feedback` table (student_id, subtask_id, timestamp, file_hash, feedback_json)
   - Re-upload → new row, old feedback preserved (history)

4. **Rubric format change**
   - Extend `graded_artifact_json` schema: add `criteria` list alongside existing `rubric` (or replace — decide on backward compat)
   - Update import/export in `import_task.py`
   - Update `docs/task_json_format.md` and `docs/shared/lernmanager/conventions.md`

5. **Admin: capstone review + grade entry**
   - Admin view: list of capstone submissions per student, with LLM feedback visible as context
   - Grade input field (1–4 or school-specific scale — TBD)
   - Grade stored in… new column on `student_subtask`? or separate `artifact_grade` table?

6. **Authoring**
   - Growing rubric convention documented in `docs/shared/mbi/conventions.md`
   - `content_checker.py` check: warn if task N criteria are a strict subset of task N-1 (i.e., nothing was added)

---

## Open Questions

**Architecture**
- [ ] DB table design for step checkbox state (student_id, subtask_id, step_index, checked)
- [ ] DB table / column design for artifact submissions — `artifact_feedback` table vs. column on `student_subtask`
- [ ] How does Flow B push results to Lernmanager? API endpoint? Direct DB write? File drop?
- [ ] Does the capstone upload replace or extend the existing quiz-based completion flow?
- [ ] Admin setting for opt-in: column on `klasse` table, or separate settings table?

**UX**
- [ ] Where does checklist feedback display — inline below upload widget, or separate result section?
- [ ] When does the upload prompt appear relative to the per-task quiz (if any)?
- [ ] What happens on re-upload — replace feedback or show history?
- [ ] What does the UI show when LLM feedback is disabled (opt-out state)? Upload still available, feedback just absent?

**Grading**
- [ ] LLM backend decision: OVHcloud Qwen3-32B (recommended — EU, €0.06/mo) vs. Mistral Large 3 (EU, €0.40/mo) vs. Mac Mini + WireGuard (cleanest DSGVO, school days only) vs. Anthropic (full DSGVO process)
- [ ] Benchmark Qwen3-32B (OVHcloud) on Unit 4 rubric for German-language checklist grading quality
- [ ] Obtain DPA from chosen EU provider (Mistral or OVHcloud) before enabling for any class
- [ ] Exact LLM prompt format for checklist output (align structure with grading-with-llm micro-prompts)
- [ ] Grade scale for teacher entry: 1–4 (grading-with-llm scale) or school's official 1–6?
- [ ] Path-aware grading for depth-model tasks (open in grading-with-llm too — see its conventions.md)

**Authoring / tooling**
- [ ] Should `content_checker.py` enforce growing rubric consistency (warn if task N adds no new criteria)?
- [ ] Backward compat: keep `rubric` field alongside new `criteria` list, or replace?

**DSGVO** (full analysis in Privacy section above)
- [ ] Obtain and review DPA (AVV) from Anthropic
- [ ] Verify Anthropic DPF certification or confirm SCCs cover EU→US transfer
- [ ] Check ThürDSB guidance on school cloud services
- [ ] Conduct or commission DPIA (Art. 35) — likely required
- [ ] Update school Datenschutzerklärung (Art. 13 transparency obligation)
- [ ] DSB / Schulleitung sign-off before enabling for any class
- [ ] Data retention policy for `artifact_feedback` table — define and document
