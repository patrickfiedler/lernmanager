# Admin Simplification Through Learning Paths

## The Core Insight

The current admin interface is complex because **admins manually do what learning paths will automate**. Today, when a teacher assigns a topic, they must:

1. Pick a topic → assign to class/student
2. Get redirected to a visibility config page
3. Manually check/uncheck which tasks each student should see
4. Optionally set "current subtask" per student (legacy, unused by students)
5. Optionally override visibility per individual student

With learning paths, **step 2–5 disappear entirely**. The student's path (Wanderweg/Bergweg/Gipfeltour) determines what's required vs. optional — and all tasks are always visible. No manual visibility configuration needed.

## What Can Be Removed or Simplified

### 1. REMOVE: The entire subtask visibility management system (4 routes, 2 templates, ~600 lines)

**Current state:** 4 routes + 421-line template + ~170 lines of JS for managing per-class and per-student subtask visibility checkboxes.

**Why it's obsolete:** Learning paths make all tasks visible to all students. The path determines required vs. optional. No manual toggling needed.

**What to keep:** A minimal "admin override" escape hatch (e.g., hide a broken task). But this can be a simple toggle on the topic detail page, not a separate management system.

| Remove | Lines saved |
|--------|-------------|
| `admin_aufgaben_verwaltung_klasse()` route | ~30 |
| `admin_aufgaben_verwaltung_schueler()` route | ~55 |
| `admin_aufgaben_verwaltung_speichern()` route | ~65 |
| `admin_aufgaben_verwaltung_reset()` route | ~15 |
| `teilaufgaben_verwaltung.html` template | 421 |
| 5 debug print statements | 5 |
| Raw SQL in route handler | ~25 |
| **Total** | **~615 lines** |

### 2. REMOVE: The `current_subtask_id` system (legacy, already unused)

**Current state:** Student detail page has a "Aktuelle Aufgabe verwalten" card that sets `student_task.current_subtask_id`. But the student view code (`student_klasse` route) **doesn't use this field at all** — it uses the visibility system instead.

**What to remove:**
- "Aktuelle Aufgabe verwalten" card from `schueler_detail.html` (~50 lines)
- `admin_schueler_aufgabe_setzen()` route (~20 lines)
- `set_current_subtask()` and `get_current_subtask()` model functions
- The duplicated `loadSubtasksForStudent()` JS function (~40 lines)

### 3. SIMPLIFY: Topic assignment flow (no more redirect-to-config)

**Current state:** Assigning a topic to a class → auto-redirect to subtask visibility page → admin must configure checkboxes before students can work.

**With learning paths:** Assign topic → done. The path handles everything. No redirect, no config step.

This removes the "interrupt workflow" pattern that confuses teachers.

### 4. SIMPLIFY: Student detail page (from 7 sections to 4)

**Current state (7 sections):**
1. Login Info
2. Classes List
3. Move Student
4. Assign Topic (+ subtask dropdown + class dropdown)
5. Current Subtask management (legacy, unused)
6. Subtask Visibility link (separate page)
7. Manual Topic Completion

**With learning paths (4 sections):**
1. Login Info + Path badge (🟢/🔵/⭐)
2. Classes & Topics (merged: show classes with active topic inline)
3. Assign Topic / Move Student (simplified: no subtask dropdown needed)
4. Manual Overrides (complete topic, change path — rare actions)

### 5. SIMPLIFY: Topic detail page (split the 455-line monolith)

**Current state:** One page with 3 forms, fragile hidden-input duplication for quiz editing, complex unsaved-changes tracking across forms.

**Opportunity (with or without learning paths):** Split into focused pages:
- **Topic basics** — name, subject, level, description, prerequisites
- **Tasks (Aufgaben)** — task list with ordering, descriptions, per-task quizzes, path assignment (🟢/🔵/⭐)
- **Materials** — upload/link/assign to tasks
- **Topic Quiz** — standalone quiz editor

This also eliminates the fragile pattern where the quiz form must duplicate all metadata fields as hidden inputs.

### 6. SIMPLIFY: Navigation (from 7 items to 4+menu)

**Current:** Dashboard | Klassen | Themen | Wahlpflicht | Aktivität | Quiz-Prüfung | Fehlerprotokolle

**Proposed:**
- **Dashboard** — overview
- **Klassen** — classes, students, topic assignment, lessons
- **Themen** — topics, tasks, materials, quizzes
- **Mehr** (dropdown) — Wahlpflicht, Aktivität, Quiz-Prüfung, Fehlerprotokolle, Passwort

This reduces cognitive load, especially on tablets.

### 7. CONSOLIDATE: Duplicated JavaScript

The `loadSubtasks()` function is copy-pasted between `klasse_detail.html` and `schueler_detail.html` (only element IDs differ). With learning paths, this function may not even be needed anymore (no subtask selection on assignment). If still needed, extract to a shared JS file.

## What Learning Paths Add to Admin UI

These are new but **simpler** than what they replace:

| New UI Element | Where | Complexity |
|----------------|-------|------------|
| Path column in task editor | Topic detail (tasks tab) | Dropdown per task: 🟢/🔵/⭐ |
| Student path display | Student detail | Read-only badge |
| Topic queue ordering | New page per class | Drag-to-reorder list |
| "Next topic" indicator | Class detail student table | "Thema 3/7" text |

**Net complexity change:** Remove ~800 lines of visibility management, add ~200 lines of path/queue UI. Significant net reduction.

## Implementation Strategy: Combine Simplification with Learning Paths

### Phase 0: Pre-cleanup (do first, independent of learning paths)
- [ ] Remove `current_subtask_id` system (already unused by students)
- [ ] Remove debug prints from `admin_aufgaben_verwaltung_schueler()`
- [ ] Move raw SQL from `admin_aufgaben_verwaltung_speichern()` into model functions
- [ ] Extract duplicated `loadSubtasks()` JS (or remove if no longer needed)
- [ ] Add `subtask_visibility` table to `init_db()` (currently only in migration)

### Phase 1: Migration (from combined plan)
- Add path/path_model/graded_artifact to subtask
- Add lernpfad to student
- Schema changes for topic progression

### Phase 2: Model changes + visibility simplification
- Implement path-based completion logic
- Modify `get_visible_subtasks_for_student()` to use paths as primary, visibility as override
- Keep visibility system as minimal admin override (not primary mechanism)

### Phase 3: Admin UI overhaul (alongside learning paths UI)
- [ ] Simplify student detail page (remove sections 5+6, add path badge)
- [ ] Simplify topic assignment (no redirect to visibility config)
- [ ] Add path dropdown to task editor
- [ ] Split topic detail page into focused sub-pages
- [ ] Simplify navigation bar
- [ ] Add topic queue page

### Phase 4: Remove old visibility UI
- [ ] Remove `teilaufgaben_verwaltung.html` and its 4 routes
- [ ] Replace with minimal "admin override" toggle (e.g., on topic detail page)
- [ ] Remove or simplify 6 visibility model functions

## Summary

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Admin routes | 42 | ~34 | -8 |
| Admin templates | 15 | ~13 | -2 |
| Largest template | 455 lines | ~200 lines | Split into focused pages |
| Visibility config pages | 2 | 0 | Replaced by path system |
| Steps to assign topic | 5 | 1 | Assign → done |
| Nav items | 7 | 4 + dropdown | Cleaner |
| Overlapping systems | 2 | 0 | Remove current_subtask_id + simplify visibility |
