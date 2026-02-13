# Plan: Lernmanager UI Improvements & Bug Fixes

## Goal
Improve student experience with clearer terminology, fix the subtask visibility bug, and add task export functionality.

## User Requests (Prioritized)

### P1: Critical Bug Fix
- **Subtask visibility bug**: Students lose assigned tasks when admin edits tasks/subtasks
- Root cause: "default-to-invisible" policy - new assignments have no visibility rules
- Fix: Auto-enable all subtasks when task is first assigned

### P2: Terminology Redesign
- Rename "Aufgabe" → "Thema" (topic)
- Rename "Teilaufgabe" → "Aufgabe" (task)
- Reduces confusion: "Aufgabe 1/2" badge + "Teilaufgabe 5" heading → clearer mental model
- **17 files** need terminology updates (templates, flash messages, navigation)

### P3: JSON Export Function
- Export tasks as JSON for backup and LLM processing
- Include: task metadata, subtasks (with time estimates), materials, quizzes, prerequisites
- Admin route: `/admin/aufgaben/export`

### P4: File Submission Instructions (Content)
- Not a code change - add clear folder/filename instructions to task content
- Keywords for automatic collection script

### P5: PDF Curriculum View (DEFERRED)
- Display curriculum PDF in admin view
- Highlight learning outcomes with LLM analysis
- Match tasks to curricular requirements
- **Deferred to separate project** ✓

### P6: Content Restructuring (After Export)
- Analyze existing tasks with export data
- Suggest how to break into smaller, self-contained units
- Add file submission instructions with folder/keyword patterns

---

## Phase 1: Bug Fix (Subtask Visibility)

### Problem Analysis
Current flow when admin assigns task:
1. `assign_task_to_student()` creates `student_task` record
2. No visibility rules created → `get_visible_subtasks_for_student()` returns empty list
3. Student sees "Weitere Aufgaben kommen bald!" instead of subtasks

### Solution
Modify `assign_task_to_student()` in `models.py` to auto-enable all subtasks:

**File: `models.py`** (around line 635-680)
```python
# After creating student_task, auto-enable all subtasks
subtasks = get_subtasks_for_task(task_id)
for subtask in subtasks:
    set_subtask_visibility_for_student(student_id, subtask['id'], True)
```

Also check: `assign_task_to_class()` for class-wide assignments.

### Verification
1. Assign a task to a student
2. Student should immediately see all subtasks
3. Edit the task (change subtask text)
4. Student should still see subtasks (visibility preserved by position)

---

## Phase 2: Terminology Update

### Mapping
| Current German | New German | English equivalent |
|----------------|------------|-------------------|
| Aufgabe | Thema | Topic |
| Teilaufgabe | Aufgabe | Task/Assignment |
| Aufgaben (nav) | Themen | Topics |

### Files to Modify (17 total)

**Student templates (2):**
- `templates/student/klasse.html` - progress text, badges, headings
- `templates/student/dashboard.html` - task cards (verify)

**Admin templates (10):**
- `templates/admin/aufgaben.html` - page title, headers
- `templates/admin/aufgabe_form.html` - form labels
- `templates/admin/aufgabe_detail.html` - subtask section headers
- `templates/admin/teilaufgaben_verwaltung.html` - visibility management
- `templates/admin/schueler_detail.html` - assignment UI
- `templates/admin/klasse_detail.html` - class task list
- `templates/admin/dashboard.html` - task count card
- `templates/admin/wahlpflicht.html` - elective groups
- `templates/admin/student_activity.html` - activity log
- `templates/admin/analytics.html` - analytics labels

**Base template (1):**
- `templates/base.html` - navigation menu "Aufgaben" → "Themen"

**Python files (3):**
- `app.py` - flash messages (~15 occurrences)
- `models.py` - schema comments
- `utils.py` - PDF report labels

**Test file (1):**
- `test_ui_integration.py` - assertion messages

### Approach
- Use search-and-replace with context awareness
- **Change URL routes** for full consistency:
  - `/admin/aufgabe/` → `/admin/thema/`
  - `/admin/aufgaben` → `/admin/themen`
  - Update `url_for()` calls throughout templates
- Update user-visible strings

---

## Phase 3: Task Export & Content Migration

### Existing Infrastructure
- **`import_task.py`** - Already handles JSON import (needs updates)
- Missing: `estimated_minutes`, `why_learn_this`, `number` fields
- Missing: Export function (companion to import)

### Migration Strategy Options

**Option A: JSON Round-Trip (Recommended)**
1. Create JSON export function (matches import format)
2. Update import to handle new fields
3. Workflow:
   - Export current tasks → JSON
   - Edit with LLM → restructured JSON
   - Import as NEW tasks (don't delete old ones)
   - Gradually transition students to new tasks
   - Archive old tasks once all students complete them
- ✅ No data loss risk - soft migration
- ✅ Works with encrypted VPS database

**Option B: SQL Direct Migration**
1. Export task tables from VPS: `sqlite3 db.sqlite .dump > tasks.sql` (filter tables)
2. Import locally
3. Edit directly
4. Export back, import on VPS
- ⚠️ Complex with SQLCipher encryption
- ⚠️ Risk of breaking student references

**Option C: Create New Tasks, Keep Old**
1. Export for reference only
2. Create restructured tasks fresh in UI
3. Assign new tasks to classes
4. Old task progress preserved until students complete
- ✅ Simplest, no import needed
- ⚠️ More manual work

### Recommended: Option A

### New Route
**File: `app.py`**
```
GET /admin/themen/export - Export all tasks as JSON
GET /admin/thema/<task_id>/export - Export single task
```

### Export Schema
```json
{
  "version": "1.0",
  "exported_at": "2026-02-04T...",
  "tasks": [
    {
      "name": "...",
      "number": 1,
      "beschreibung": "...",
      "lernziel": "...",
      "fach": "...",
      "stufe": "...",
      "kategorie": "pflicht|bonus",
      "why_learn_this": "...",
      "subtasks": [
        {
          "beschreibung": "...",
          "reihenfolge": 1,
          "estimated_minutes": 15
        }
      ],
      "materials": [
        {
          "typ": "link|datei",
          "pfad": "...",
          "beschreibung": "..."
        }
      ],
      "quiz": {
        "questions": [...]
      },
      "prerequisites": ["task_name_1", ...],
      "follow_ups": ["task_name_2", ...]
    }
  ]
}
```

### New Model Function
**File: `models.py`**
- `export_task_to_dict(task_id)` - Single task with all related data
- `export_all_tasks()` - All tasks grouped by subject/level

### Update Existing Import Script
**File: `import_task.py`** - Add support for:
- `estimated_minutes` in subtasks (line 206)
- `why_learn_this` field
- `number` field for task ordering
- `follow_ups` (task_folge relationships)

### Admin UI
Add export button to:
- `templates/admin/themen.html` (was aufgaben.html - export all)
- `templates/admin/thema_detail.html` (was aufgabe_detail.html - export single)

### Soft Migration Workflow
```
1. Run export → tasks_backup_2026-02-04.json
2. LLM analysis → restructured_tasks.json (smaller units, clear instructions)
3. Import new tasks (creates new IDs, doesn't touch existing)
4. Admin assigns new "Themen" to classes
5. Students gradually complete old tasks, start new ones
6. Admin archives/deletes old tasks when safe
```

---

## Phase 4: File Submission Instructions (Content Change)

This is a **content authoring task**, not code:
- Add clear instructions to subtask descriptions
- Specify: folder path, filename keyword
- Example: "Speichere deine Datei im Ordner `Abgaben/Thema3` mit dem Schlüsselwort `reflexion` im Dateinamen"

No code changes required - just task content updates.

---

## Phase 5: Content Restructuring Assistance

After export is ready, I'll help you:

1. **Export current tasks** to JSON
2. **Analyze task structure**:
   - Identify tasks that could be split into smaller units
   - Suggest logical breakpoints (5-15 min chunks for student momentum)
   - Ensure each unit is self-contained with clear completion criteria
3. **File submission patterns**:
   - Identify tasks requiring digital submissions
   - Suggest folder/keyword conventions for your collection script
   - Example: `Abgaben/{Thema}/{Nachname}_{keyword}.{ext}`

### Output
- Markdown analysis document with restructuring suggestions
- You review and approve changes
- I help update task content in the database

---

## Phase 6: PDF Curriculum View (DEFERRED)

**Deferred to separate project**

Would require:
1. PDF upload and storage for curriculum documents
2. PDF.js or similar for in-browser rendering
3. Text extraction (PDF parsing or OCR)
4. LLM integration for learning outcome identification
5. Task-to-outcome matching algorithm
6. Highlighting/annotation UI

Estimated: 20+ hours of development

---

## Implementation Order

1. **Bug fix** (P1) - Critical, affects current users
2. **Terminology + URL routes** (P2) - Improves clarity, full consistency
3. **JSON Export** (P3) - Enables backup before restructuring
4. **Content restructuring** (P6) - Analyze and suggest smaller task units
5. ~~Curriculum view~~ - Deferred to separate project

---

## Verification Plan

### Bug Fix
- [ ] Assign new task → student sees all subtasks immediately
- [ ] Edit task → student still sees subtasks
- [ ] Re-assign same task → no duplicate visibility rules

### Terminology
- [ ] Student view shows "Aufgabe 1/2" (referring to tasks within topic)
- [ ] Admin nav shows "Themen" instead of "Aufgaben"
- [ ] Flash messages use new terminology
- [ ] Run existing tests, update assertions

### Export
- [ ] Export single task → valid JSON with all data
- [ ] Export all tasks → complete curriculum backup
- [ ] Re-import exported JSON (future feature)

---

## Decisions Made ✓

1. **URL routes**: Change for full consistency (`/admin/aufgabe/` → `/admin/thema/`)
2. **Priority**: Bug fix → Terminology + URLs → Export → Content restructuring
3. **PDF curriculum**: Deferred to separate project
4. **Content help**: I'll help analyze and suggest task restructuring after export is ready
5. **Migration strategy**: JSON soft migration (export → LLM restructure → import as new tasks)

---

## Files to Modify (Summary)

### Phase 1: Bug Fix
- `models.py` - `assign_task_to_student()`, `assign_task_to_class()`

### Phase 2: Terminology + URLs
- `app.py` - Route names, flash messages (~25 changes)
- `models.py` - Comments only
- `utils.py` - PDF report labels
- `templates/base.html` - Navigation
- `templates/admin/*.html` - 10 template files
- `templates/student/*.html` - 2 template files
- `test_ui_integration.py` - Assertions

### Phase 3: Export/Import
- `models.py` - Add `export_task_to_dict()`, `export_all_tasks()`
- `app.py` - Add export routes
- `import_task.py` - Update for new fields
- `templates/admin/themen.html` - Export button

### Phase 5: Content Restructuring
- No code changes - analysis and content authoring
