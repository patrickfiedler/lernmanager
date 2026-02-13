# Instruction: Dual Lernziel Support in Lernmanager

**Date:** 2026-02-13
**Context:** The MBI curriculum now exports two versions of each unit's Lernziel (learning goal):
- **`lernziel`** — Teacher-centric: „Die Schülerinnen und Schüler können…"
- **`lernziel_schueler`** — Student-centric: „Du lernst…"

This document describes what needs to change in the Lernmanager app to support both versions.

## 1. JSON Format Change

The `task_json_format.md` spec now includes a new optional field:

```json
{
  "task": {
    "name": "A - Sicher und schlau im Netz",
    "lernziel": "Die Schülerinnen und Schüler können manipulierte Bilder und Fake News erkennen...",
    "lernziel_schueler": "Du lernst, wie du manipulierte Bilder und Fake News erkennst...",
    ...
  }
}
```

**Backward compatible:** If `lernziel_schueler` is missing, fall back to `lernziel` everywhere.

## 2. Database Change

Add one column to the `task` table:

```sql
ALTER TABLE task ADD COLUMN lernziel_schueler TEXT;
```

That's it. The column is nullable — old records keep `NULL` and the app falls back to `lernziel`.

## 3. Import Script Change (`import_task.py`)

In the function that reads the JSON and creates/updates a `task` record, add handling for the new field:

```python
# Where the task dict is read from JSON and mapped to DB fields:
lernziel_schueler = task_data.get("lernziel_schueler")  # None if absent

# Where the DB record is created/updated:
# Add lernziel_schueler to the INSERT/UPDATE statement
```

The exact location depends on how `import_task.py` maps JSON fields to the database. The pattern is identical to how `lernziel` is already handled — just one more field.

## 4. App Display Logic

Use this rule:

| View | Which field to show |
|------|-------------------|
| **Student-facing** (Thema page, dashboard) | `lernziel_schueler` if present, otherwise `lernziel` |
| **Teacher-facing** (admin panel, reports, grading) | `lernziel` (teacher version always) |

In code (pseudocode):

```python
def get_display_lernziel(task, viewer_is_teacher=False):
    if viewer_is_teacher:
        return task.lernziel
    return task.lernziel_schueler or task.lernziel
```

### Where in the app?

The Lernziel is currently displayed in one place: the Thema detail page header. If the viewer is a student, show the `lernziel_schueler` version. If the viewer is a teacher (admin), show `lernziel`.

If there's no separate teacher view yet, just show `lernziel_schueler` (with fallback) everywhere — students are the primary audience.

## 5. Migration for Existing Units

The existing Kapitel 1 and 2 JSON files (`kapitel_01.json`, `kapitel_02.json`) don't have `lernziel_schueler` yet. Two options:

- **Option A (recommended):** Add `lernziel_schueler` to those JSON files and re-import. The student-centric versions already exist in the design docs:
  - Kapitel 1: „Du lernst, wie du dich am Computer anmeldest, die Lernplattform nutzt, Hardware und Software benennst, Dateien sinnvoll ablegst, sichere Passwörter erstellst und ein formatiertes Dokument mit Bild abgibst."
  - Kapitel 2: „Du lernst, wie du Scratch Desktop bedienst, dein Projekt speicherst und wieder öffnest, eine Figur mit Blöcken bewegst und sprechen lässt, Bühnenbilder und Klänge einsetzt und eine eigene animierte Geschichte erzählst."
- **Option B:** Leave them as-is. The fallback logic means `lernziel` is shown when `lernziel_schueler` is NULL. Students see the teacher version, which is acceptable.

## 6. Summary of Changes

| Component | Change | Effort |
|-----------|--------|--------|
| `task_json_format.md` | New field documented | ✅ Done |
| Database schema | `ALTER TABLE task ADD COLUMN lernziel_schueler TEXT` | 1 line |
| `import_task.py` | Read + store one more field | ~3 lines |
| App template/view | Show `lernziel_schueler` for students | ~5 lines |
| Existing JSON files | Optionally add `lernziel_schueler` | Copy from design docs |

Total effort: minimal. The design is intentionally simple — one new optional column, one fallback rule.
