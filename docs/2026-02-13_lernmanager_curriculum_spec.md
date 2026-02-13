# Lernmanager — Curriculum Structure & Import Spec

This document describes the curriculum structure, learning paths, and JSON import format for the MBI (Medienbildung und Informatik) course, grades 5/6. Use it to implement full support in the Lernmanager app.

## 1. Content Hierarchy

```
Thema (= Kapitel, DB table: task)
├── Aufgabe 1 (DB table: subtask) + optional per-task quiz
├── Aufgabe 2 + optional per-task quiz
├── ...
├── Aufgabe N + optional per-task quiz
├── Materialien (links, files)
└── optional Themen-Quiz (synthesis quiz for the whole Kapitel)
```

- **10 Themen** (Kapitel 1–10), completed over 2 school years (Kl.5 + Kl.6)
- Each Thema has **3–8 Aufgaben**
- Each Aufgabe = 1 lesson = 45 minutes
- Themen have prerequisites (linear with some branching)
- Total: **67 Aufgaben** across all Themen

## 2. Learning Paths

Three cumulative difficulty paths. Every student sees all Aufgaben, but only their path's Aufgaben are required.

| Path | Label | Emoji | Tasks | % of total | Description |
|------|-------|-------|-------|------------|-------------|
| Wanderweg | 🟢 | 🥾 | 33 | ~49% | Foundational. Everyone does these. Enough to pass. |
| Bergweg | 🔵 | ⛰️ | 58 | ~87% | Full curriculum. The expected/recommended path. |
| Gipfeltour | ⭐ | 🏔️ | 67 | 100% | Everything. For students who want maximum depth. |

### Path rules

- **Cumulative:** Bergweg includes all Wanderweg tasks. Gipfeltour includes all Bergweg tasks.
- **The path label on a task = the LOWEST path that includes it.**
  - A task labeled 🟢 Wanderweg → done by ALL students (W + B + G)
  - A task labeled 🔵 Bergweg → done by Bergweg + Gipfeltour only
  - A task labeled ⭐ Gipfeltour → done by Gipfeltour only
- **Students choose their path** ("Du wählst deinen Weg"). They can upgrade mid-unit.
- **All tasks are visible** to all students, regardless of path. Non-required tasks are visually marked as optional (greyed out, dimmed, or labeled "optional für deinen Weg").

### Per-task path model

Each Aufgabe uses one of two models:

| Model | Meaning | Example |
|-------|---------|---------|
| **skip** | Lower paths don't do this task at all. | EVA-Prinzip (🔵 Bergweg): Wanderweg students skip it entirely. |
| **depth** | All paths do this task, but with different expectations. | Computer-Steckbrief (🟢 Wanderweg, depth): all paths submit, but grading expectations differ by path. |

For **depth** tasks:
- The task description itself contains tiered expectations ("Für eine bessere Note:", "Für die beste Note:")
- The grading rubric maps grades to path-aligned criteria
- The app does NOT need to show different task descriptions per path — one description, with bonus sections clearly marked, serves all paths

### JSON representation

```json
{
  "beschreibung": "...",
  "reihenfolge": 0,
  "estimated_minutes": 45,
  "path": "wanderweg",
  "path_model": "skip",
  "quiz": { ... }
}
```

New fields per subtask:

| Field | Required | Type | Values |
|-------|----------|------|--------|
| `path` | yes | string | `"wanderweg"`, `"bergweg"`, or `"gipfeltour"` |
| `path_model` | no | string | `"skip"` (default) or `"depth"` |

**`path`** = the lowest path that includes this task.
**`path_model`** = `"skip"` means lower paths don't do it; `"depth"` means all paths do it but with different expectations.

When `path_model` is `"depth"`:
- The task is required for ALL paths (regardless of the `path` label)
- The `path` label still indicates the lowest path, but it only affects *grading expectations*, not visibility
- Grading criteria are embedded in the task description and in the `graded_artifact.rubric` field

## 3. Graded Artifacts

Some Aufgaben produce a graded digital artifact (document, image, Scratch project). These are the high-stakes assessments (~10 per school year, ~20 total).

### JSON representation

Subtasks that are graded artifacts include an additional field:

```json
{
  "beschreibung": "...",
  "reihenfolge": 6,
  "path": "wanderweg",
  "path_model": "depth",
  "graded_artifact": {
    "keyword": "computer-steckbrief",
    "format": [".docx", ".odt"],
    "rubric": "Prüfe: (1) Sind die vier Pflichtabschnitte vorhanden und inhaltlich korrekt? (2) Wie detailliert sind die Beschreibungen? (3) Gibt es EVA-Beispiele, Tabellen oder Netzwerk-Erklärungen? (4) Gibt es persönliche Reflexion oder Zusatzwissen? (5) Ist das Dokument sauber formatiert? Vergib Note 1–4 nach Kriterienliste im Aufgabentext."
  },
  "quiz": { ... }
}
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `graded_artifact` | no | object | Present only if this task is a graded artifact |
| `.keyword` | yes | string | Unique identifier, used in filename matching (e.g. file must contain this keyword) |
| `.format` | yes | array | Accepted file extensions |
| `.rubric` | yes | string | LLM grading instructions. References criteria in the task description. |

### Grading workflow (existing, not changed)

1. Student saves file to network drive with correct name (contains keyword)
2. Collection script picks up files
3. LLM grades using the rubric
4. Result (Note 1–4) is fed back to Lernmanager

Graded artifacts are always **depth model** — all paths submit, grading expectations differ.

## 4. Quiz System

### 4.1 Per-task quiz

Each Aufgabe can have a quiz with 2–4 questions. Students take it after completing the task.

```json
"quiz": {
  "questions": [
    {
      "text": "Welches davon ist Software?",
      "options": ["Monitor", "Tastatur", "Microsoft Word", "USB-Kabel"],
      "correct": [2]
    },
    {
      "type": "fill_blank",
      "text": "Teile des Computers, die man anfassen kann, nennt man ___.",
      "answers": ["Hardware", "hardware"]
    },
    {
      "type": "short_answer",
      "text": "Was ist der Unterschied zwischen Hardware und Software?",
      "rubric": "Hardware = physische Teile, Software = Programme. Kernaussage: Hardware anfassbar, Software nicht."
    }
  ]
}
```

**Behavior:**
- Low-stakes, not graded (pass/fail for progress tracking)
- Pass threshold: ~70% correct (rounded down: 2 of 3, 3 of 4)
- `subtask_quiz_required` (Thema-level flag): if `true`, students must pass the quiz to mark the Aufgabe as complete
- Students can retry quizzes

### 4.2 Synthesis quiz (Thema-level)

Each Thema can have a synthesis quiz in the top-level `quiz` field. This is the "Abschlussquiz" for the whole Kapitel.

```json
"quiz": {
  "questions": [ ... ]  // ~10-12 questions, "best of" from task quizzes
}
```

**Behavior:**
- Available after all required Aufgaben for the student's path are complete
- Same pass threshold (~70%)
- Questions are also used for **spaced repetition** (see below)

### 4.3 Spaced repetition pool

Both per-task and synthesis quiz questions feed into a spaced repetition pool.

**Expected app behavior:**
- At the start of each lesson, show a **weekly synthesis quiz** (~5 questions)
- Draw questions from recently completed tasks (not just the current Thema)
- Prioritize questions the student previously answered incorrectly
- Low-stakes, ungraded — purpose is reinforcement, not assessment

### 4.4 Question types

| Type | `type` field | Required fields | Grading |
|------|-------------|-----------------|---------|
| Multiple choice | omitted (default) | `text`, `options`, `correct` | Auto: check selected index against `correct` array |
| Fill-in-the-blank | `"fill_blank"` | `text`, `answers` | Auto: exact match against `answers` list. If no match → LLM fallback |
| Short answer | `"short_answer"` | `text`, `rubric` | LLM grades against `rubric`. Fallback: award point + flag for teacher review |

- `correct`: array of 0-based indices. Usually one correct answer; multiple for "select all that apply"
- `answers`: array of accepted strings (case-sensitive — include variants!)
- `rubric`: description of expected answer for LLM grading. Describe key points, not exact wording.
- Optional on any question: `"image": "/path/to/image.png"` for visual questions

## 5. Materials

Links and files attached to a Thema, optionally scoped to specific Aufgaben.

```json
"materials": [
  {
    "typ": "link",
    "pfad": "https://example.com/resource",
    "beschreibung": "Verbraucherzentrale: Sichere Passwörter",
    "subtask_indices": [4]
  }
]
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `typ` | yes | string | `"link"` or `"datei"` (files are manual upload only) |
| `pfad` | yes | string | URL or file path |
| `beschreibung` | no | string | Short description |
| `subtask_indices` | no | array | Which Aufgaben this material belongs to (by `reihenfolge` value). Omit = visible everywhere. |

## 6. Complete JSON Structure

```json
{
  "task": {
    "name": "1 - Willkommen am Computer",
    "number": 1,
    "beschreibung": "Thema description (Markdown)",
    "lernziel": "Learning objectives",
    "why_learn_this": "Student-facing motivation text",
    "fach": "MBI",
    "stufe": "5/6",
    "kategorie": "pflicht",
    "subtask_quiz_required": true,
    "subtasks": [
      {
        "beschreibung": "**Task title:** Full task description (Markdown)",
        "reihenfolge": 0,
        "estimated_minutes": 45,
        "path": "wanderweg",
        "path_model": "skip",
        "quiz": { "questions": [ ... ] }
      },
      {
        "beschreibung": "...",
        "reihenfolge": 1,
        "estimated_minutes": 45,
        "path": "bergweg",
        "path_model": "skip",
        "graded_artifact": {
          "keyword": "artifact-name",
          "format": [".docx"],
          "rubric": "LLM grading instructions..."
        },
        "quiz": { "questions": [ ... ] }
      }
    ],
    "materials": [ ... ],
    "quiz": { "questions": [ ... ] },
    "voraussetzungen": ["Previous Thema name"]
  }
}
```

### Field reference — Thema (task)

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | yes | string | Format: `"N - Title"` (number + title) |
| `number` | no | int | Sort order |
| `beschreibung` | yes | string | Markdown. Short overview for students. |
| `lernziel` | no | string | Learning objectives (teacher-facing) |
| `why_learn_this` | no | string | Student-facing motivation text |
| `fach` | yes | string | `"MBI"` |
| `stufe` | yes | string | `"5/6"` |
| `kategorie` | no | string | `"pflicht"` (default) or `"bonus"` |
| `subtask_quiz_required` | no | bool | Must task quizzes be passed? Default: `true` |
| `subtasks` | no | array | Ordered list of Aufgaben |
| `materials` | no | array | Links and files |
| `quiz` | no | object | Synthesis quiz (Abschlussquiz) |
| `voraussetzungen` | no | array | Names of prerequisite Themen |

### Field reference — Aufgabe (subtask)

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `beschreibung` | yes | string | Markdown. Start with `**Title:**`. Full student-facing instructions. |
| `reihenfolge` | no | int | Sort position (0-based) |
| `estimated_minutes` | no | int | Expected time (usually 45) |
| `path` | yes | string | Lowest path: `"wanderweg"`, `"bergweg"`, `"gipfeltour"` |
| `path_model` | no | string | `"skip"` (default) or `"depth"` |
| `graded_artifact` | no | object | Present if this task is a graded artifact |
| `quiz` | no | object | Per-task quiz |

## 7. App Behavior Summary

### What the app must do

| Feature | Behavior |
|---------|----------|
| **Path selection** | Student picks Wanderweg, Bergweg, or Gipfeltour. Can upgrade anytime. |
| **Task visibility** | ALL tasks visible to all students. Non-required tasks marked as optional. |
| **Path markers** | Show 🟢/🔵/⭐ next to each Aufgabe based on `path` field. |
| **Skip model** | If student's path < task's path → task shown as optional, not required for progress. |
| **Depth model** | If `path_model: "depth"` → task is required for ALL paths. Different grading expectations are in the task text. |
| **Per-task quiz** | Show quiz after task completion. Block progress if `subtask_quiz_required: true`. Allow retries. |
| **Synthesis quiz** | Unlock after all required tasks for student's path are done. ~70% pass threshold. |
| **Spaced repetition** | Weekly quiz (~5 questions) drawn from completed task/synthesis quiz pools. Prioritize previously incorrect answers. |
| **Graded artifact** | Display keyword and format. Artifact is collected from network drive (not uploaded). Show grade when available. |
| **Materials** | Show materials scoped to their subtask(s), or globally if no `subtask_indices`. |
| **Prerequisites** | Lock a Thema until all listed `voraussetzungen` are completed. |

### Progress tracking per path

A student's progress through a Thema depends on their chosen path:

- **Wanderweg student in Kapitel 1:** Must complete tasks 1,2,4,5,6,7 (6 of 7). Task 3 (EVA, 🔵) is optional.
- **Bergweg student in Kapitel 1:** Must complete all 7 tasks.
- **Gipfeltour student in Kapitel 1:** Must complete all 7 tasks (same as Bergweg here; in other Kapitel, Gipfeltour has additional tasks).

The app determines required tasks by comparing the student's path against each task's `path` field:
- If `task.path` ≤ `student.path` → required
- If `task.path` > `student.path` → optional (unless `path_model: "depth"`, then always required)

Path ordering: `wanderweg` < `bergweg` < `gipfeltour`

## 8. Import

```bash
python import_task.py kapitel_01.json          # Import one Kapitel
python import_task.py --dry-run kapitel_01.json # Validate without importing
python import_task.py --batch units/            # Import all JSON files in folder
python import_task.py --list                    # List existing Themen
```

- Duplicates (same name + fach + stufe) are skipped
- `voraussetzungen` reference Themen by name — prerequisite must already exist
- Files are UTF-8 encoded
