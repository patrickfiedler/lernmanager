# Future Features Plan: Implement Todo List Features

## Goal
Implement remaining features and improvements from todo.md to enhance Lernmanager functionality.

## Current Status Analysis

### ✅ Completed
- Fix task sorting (1-2-3-10) - Commit `5118ca7`
- Class assessment visual indicators - Commit `5118ca7`
- 502 file upload error - Was database permissions issue, resolved
- **Error logging functionality** - Commit `bd64505` (Phase 4)
- **Date picker German format** - Commit `0560a52` (Phase 2)
- **Dashboard schedule filter** - Commit `0560a52` (Phase 3)
- **Class schedule system** - Implemented in student assessment improvements
- **Usage analytics & activity logging** - Commit `7720a2a` (Phase 5)
- **PDF progress reports** - Commit `2183568` (Phase 6)

### 📋 Remaining Items

#### Features
- [x] ~~Student progress reports as PDF (per class and per student)~~ - Phase 6 complete

#### Major Improvements (Researched & Planned)

##### 1. Student Experience Redesign ⭐ **READY TO IMPLEMENT**
- [x] Research and design complete
- [x] Mockups created and approved (hybrid design)
- [x] Implementation roadmap created (`student_redesign_roadmap.md`)
- [ ] Implementation: Database schema (add `why_learn_this` field)
- [ ] Implementation: Admin interface for new field
- [ ] Implementation: Redesigned student task view
- [ ] Implementation: Updated styling
- [ ] Testing and deployment

**Estimated effort:** 20-25 hours (3-4 full work days)
**Impact:** High - transforms student engagement and clarity
**Priority:** High - addresses core user feedback

##### 2. Database Performance Optimization
- [x] Research complete (`improvements_notes.md`)
- [ ] Implementation: Request-level connection caching
- [ ] Measurement: Profile current performance
- [ ] Optional: Connection pooling if proven necessary

**Recommendation:** Keep encryption, implement request-level caching
**Estimated effort:** 2-4 hours
**Impact:** Low-Medium - 2-4ms improvement per request
**Priority:** Medium - quick win after student redesign

##### 3. URL Improvements (Human-Friendly URLs)
- [x] Research complete (`improvements_notes.md`)
- [ ] Implementation: NOT RECOMMENDED

**Recommendation:** Keep numeric IDs, improve UI with breadcrumbs
**Reasoning:** Internal school app, migration risk not worth benefit
**Alternative:** Improved breadcrumbs (included in student redesign)
**Priority:** Low - handled by other improvements

#### Other Improvements
- [x] ~~Student view: show only current/first subtask~~ - Addressed in redesign
- [ ] Student view: visual learning map of tasks
- [x] ~~Admin: assign particular subtasks to classes/students~~ - Already implemented
- [ ] Admin: add app URL to batch-imported student credentials
- [ ] Admin: allow individual students to see all tasks (optional)
- [ ] **Admin: curriculum alignment page** - Show how topics/tasks map to curriculum learning goals
  - Display alignment between app content and official curriculum
  - Helps teachers ensure coverage of required learning objectives
  - Potentially show gaps or overlaps
  - **Priority:** Medium - useful for planning and compliance

## Recommended Implementation Order

1. ~~**Date Picker Format**~~ ✅ Complete
2. ~~**Error Logging**~~ ✅ Complete
3. ~~**Usage Analytics**~~ ✅ Complete
4. ~~**Class Schedule**~~ ✅ Complete
5. **PDF Reports** - Next priority (Phase 6)
6. **Student view improvements** - Lower priority
7. **Admin improvements** - As needed

---

*This plan is saved for future implementation. See task_plan.md for current work.*
