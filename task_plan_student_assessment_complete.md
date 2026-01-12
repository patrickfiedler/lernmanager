# Task Plan: Improve Student Progress Tracking Page

## Goal
Enhance the unterricht (student assessment) page with better visibility, weekly navigation, manual save, and improved UX.

## User Requirements

### 1. Attendance Checkboxes ✓
- Hard to see currently
- Need visible labels/text
- Make it obvious what the toggle means

### 2. Grey Out When Absent ✓
- When student marked absent, disable rating buttons
- Visual indication that ratings don't apply
- **Clear ratings if student marked absent after having ratings**

### 3. Weekly Navigation ✓
- Add Previous/Next buttons around date picker
- Jump by 1 week (not 1 day)
- Implement class schedule (day of week per class)
- Allow flexible date changes
- **Start week on Monday in date picker**

### 4. Manual Save ✓
- Remove auto-save on button click
- Add "Speichern" (Save) button
- Warn before leaving with unsaved changes
- Visual indicator of unsaved changes

### 5. Additional UX Improvements
- To be identified during planning

## Phases

- [x] Phase 1: Explore current implementation
- [x] Phase 2: Design improvements and UX enhancements - ALL improvements approved
- [x] Phase 3: Implement attendance visibility improvements
- [x] Phase 4: Implement grey-out and clear ratings for absent students
- [x] Phase 5: Design and implement class schedule system
- [x] Phase 6: Implement weekly navigation with Monday start
- [x] Phase 7: Implement manual save with unsaved change tracking
- [x] Phase 8: Implement unsaved changes warning
- [x] Phase 9: Test all improvements thoroughly
- [x] Phase 10: Deploy and verify

## Key Questions

1. **Attendance Toggle:**
   - What labels? "Anwesend" / "Abwesend"?
   - Keep toggle or switch to buttons/checkbox?

2. **Clear Ratings on Absent:**
   - Set to NULL or default values?
   - Show confirmation before clearing?
   - Should has_been_saved stay 1 or reset to 0?

3. **Class Schedule:**
   - New database table: `class_schedule` with klasse_id and weekday?
   - Where to manage schedules (class detail page)?
   - Weekday: 0=Monday, 6=Sunday (ISO 8601 standard)?
   - What if no schedule set - fallback to +1 day?

4. **Manual Save:**
   - Save all students at once (batch update)?
   - Track changed rows with JavaScript?
   - Visual indicator: yellow border, asterisk, button color?
   - Show "X Änderungen nicht gespeichert" message?

5. **Date Picker Week Start:**
   - HTML5 date input doesn't control week start
   - Need custom date picker widget?
   - Or just visual/JS enhancement?

6. **Additional UX Ideas:**
   - Keyboard shortcuts (Tab through students, Ctrl+S to save)?
   - Bulk actions (mark all present)?
   - Quick comment templates?
   - Visual summary (X of Y students evaluated)?
   - Save confirmation message?
   - Undo last save?

## Decisions Made

### Phase 1 Analysis Complete
- **Current auto-save**: Triggers on every button/field change
- **Attendance toggle**: Styled label with no text (visibility issue confirmed)
- **No disabled state**: Ratings remain clickable even when absent
- **Date picker**: HTML5 input, changes reload page
- **JavaScript structure**: Three functions (toggleAttendance, setRating, updateComment) all call saveStudent()

### Proposed Technical Approach

**1. Class Schedule** (new feature)
- Add `class_schedule` table: klasse_id, weekday (0-6, Monday=0)
- Manage in class detail page
- Use ISO 8601 weekday standard

**2. Attendance Visibility**
- Replace hidden toggle with visible checkbox + label
- Show "Anwesend" / "Abwesend" text
- Green checkmark icon when present

**3. Grey Out Absent**
- Add `.disabled` class to rating buttons when absent
- Disable buttons with `disabled` attribute
- Clear ratings to NULL when marking absent
- Set has_been_saved = 0 when cleared

**4. Manual Save**
- Track changes in JavaScript Set (unsavedChanges)
- Remove saveStudent() calls from onclick handlers
- Add "Speichern" button that calls saveAll()
- Yellow border on changed rows
- Show count: "3 Änderungen nicht gespeichert"
- beforeunload warning if unsaved

**5. Weekly Navigation**
- Add ← / → buttons around date picker
- Calculate next/previous based on schedule
- Fallback to ±7 days if no schedule
- Keep date picker for manual date selection

## Errors Encountered
(To be logged as they occur)

## Proposed Additional UX Improvements

Beyond the requirements, I suggest adding:

1. **Visual Summary**: "5 von 15 Schülern bewertet" - Shows evaluation progress
2. **Bulk Actions**: "Alle als anwesend markieren" button - Quick action for full attendance
3. **Keyboard Shortcuts**:
   - Tab to navigate through students
   - Ctrl+S to save
   - Number keys (1,2,3) for ratings when row focused
4. **Row Highlighting**: Yellow/orange border for rows with unsaved changes
5. **Save Confirmation**: Toast notification "Änderungen gespeichert ✓"
6. **Quick Comments**: Dropdown with common phrases like "Sehr aktiv", "Gut mitgearbeitet", etc.

**User Decision: Include ALL improvements (1-6)**

## Implementation Order

1. **Phase 3**: Attendance visibility (checkbox + label)
2. **Phase 4**: Grey-out absent + clear ratings + disabled state
3. **Phase 5**: Class schedule database + management UI
4. **Phase 6**: Weekly navigation with prev/next buttons
5. **Phase 7**: Manual save + unsaved tracking + row highlighting
6. **Phase 8**: Unsaved changes warning (beforeunload)
7. **Phase 9**: Visual summary + bulk actions
8. **Phase 10**: Keyboard shortcuts (Tab, Ctrl+S, number keys)
9. **Phase 11**: Save confirmation toast + quick comments dropdown

## Progress Update

### Phases 3-4 Complete
- ✅ Attendance now shows visible checkbox + "Anwesend" label + checkmark icon
- ✅ Rating buttons grey out when student marked absent
- ✅ Ratings cleared automatically when marking absent
- ✅ Comment field disabled for absent students
- ✅ UI initializes correctly on page load

## Current Status
🎉 **ALL PHASES COMPLETE** - Task successfully finished!
**Deployed and verified** - All improvements working on production server
**Commits**: eea29d0 (main features) + 36525f3 (deployment script fix)

## 🎉 MILESTONE: Critical Features Complete
Phases 5-8 are fully implemented:
- ✅ Class schedule system (set weekly meeting day per class)
- ✅ Weekly navigation (prev/next buttons jump based on schedule)
- ✅ Manual save (no more auto-save, visual feedback for unsaved changes)
- ✅ Unsaved changes warning (prevents accidental data loss)

## Deployment Script Fix (COMPLETE ✅)
**Issue**: update.sh fails at step 3/7 with "fatal: detected dubious ownership in repository"
**Cause**: Git security feature prevents operations when ownership mismatch detected
**Solution**:
- ✅ Add git config --global --add safe.directory before git operations
- ✅ Verify repository ownership (stat -c '%U' .git vs expected owner)
- ✅ Capture and display git output with error handling
- ✅ Provide helpful error message with fix command if ownership wrong
**Committed**: 36525f3 - improve update.sh: add ownership checks and git error handling

### Phase 5 Summary
- ✅ Added `class_schedule` table with klasse_id and weekday (0=Monday, 6=Sunday)
- ✅ Created model functions: get_class_schedule(), set_class_schedule(), delete_class_schedule()
- ✅ Added schedule management UI to class detail page (dropdown with Monday-Sunday)
- ✅ Created admin_klasse_schedule route to handle schedule updates
- ✅ Schedule is optional per class, allows flexible date changes

### Phase 6 Summary
- ✅ Added datetime import to models.py
- ✅ Created get_next_class_date() - calculates next class date based on schedule
- ✅ Created get_previous_class_date() - calculates previous class date based on schedule
- ✅ Logic: If schedule exists, finds next/prev occurrence of weekday; otherwise ±7 days
- ✅ Added admin_unterricht_next() and admin_unterricht_prev() routes
- ✅ Added ← and → navigation buttons around date picker in unterricht.html
- ✅ Date picker still available for manual date selection (flexibility maintained)

### Phase 7 Summary
- ✅ Removed auto-save from setRating() and updateComment() functions
- ✅ Added JavaScript Set (unsavedChanges) to track student IDs with changes
- ✅ Created markAsChanged() function to add students to unsaved set
- ✅ Added "Speichern" button with onclick handler for saveAll()
- ✅ Implemented updateUnsavedCount() to show "X Änderung(en) nicht gespeichert"
- ✅ Button changes to warning color (yellow) when there are unsaved changes
- ✅ Button disabled when no changes, enabled when changes exist
- ✅ Updated saveStudent() to return promise and remove from unsaved set on success
- ✅ Implemented saveAll() batch save with feedback ("Speichern..." → "✅ Gespeichert!")
- ✅ Added CSS for .unsaved-row with yellow border and background highlighting
- ✅ Changed toggleAttendance, setRating, updateComment to use markAsChanged instead of saveStudent

### Phase 8 Summary
- ✅ Added beforeunload event listener to warn when leaving page
- ✅ Warning only shows if unsavedChanges.size > 0
- ✅ Uses event.preventDefault() and event.returnValue for browser compatibility
- ✅ German message: "Sie haben nicht gespeicherte Änderungen. Möchten Sie die Seite wirklich verlassen?"
- ✅ Prevents accidental data loss from navigating away or closing tab
