# UX Investigation — Classroom Observation 2026-02

**Date:** 2026-02-23 (first live classroom lesson)
**Method:** Teacher questionnaire + code analysis
**Context:** Production DB anonymized, full class in session

---

## Findings Summary

### A-level — Regularly a problem

| # | Issue | Root cause | Fix |
|---|-------|-----------|-----|
| 4 | Progress dots not understood | No legend or introduction | P4: Add dot legend below dot row |
| 6 | Quiz gating (blocking progress) not understood | Concept invisible — students experience "Weiter broken" | P3: Inline explanation + retry note |
| 12 | Materials section not opened | Was collapsed by default | Already fixed (open attribute present) |
| 13 | Task descriptions too hard/long | Authoring problem | Content fix in MBI repo |
| 14 | "Fertig wenn" vague/ignored | Authoring problem | Authoring rule added to mbi/conventions.md |
| 19 | "Weiter lernen →" button not clicked — students ask teacher | Button not visually dominant; competes with practice card | P1: Full-width blue CTA |
| 23 | Easy Reading Mode found by wrong students | Buried in Settings | P6: Passive hint on dashboard |

### B-level — Problem for some students

| # | Issue | Root cause | Fix |
|---|-------|-----------|-----|
| 2 | Warmup: students afraid to answer, get stuck | No signal that warmup is consequence-free | P5: "Kein Druck — wird nicht bewertet" |
| 16 | Quiz failure discouraging for anxious students | Students don't know retrying is unlimited | P5: Retry-free message at failure + before quiz |
| 17 | After passing quiz, unclear where to go | CTA not prominent enough | P7: Full-width btn-block CTA on result page |

### Notable side-observation

Q21: Some students found **practice mode** before finding "Weiter lernen →". Practice card had equal visual weight to the primary learning CTA — hierarchy wrong. Fixed by demoting practice to `btn-secondary`.

### Not-issues (deprioritized)

- Mobile (desktop-only use so far)
- Subtask quiz `?` dots (no subtask quizzes in current content)
- Diamond dots (no Zusatz tasks in current content)
- Double-submit (mostly solved by faster loading)
- LLM grading, multiple classes, navigation buttons

---

## Code Changes Applied (2026-02-23)

### P0 — Consistent action color
- All primary "do this next" buttons: `btn-primary` (blue `#2563eb`)
- Changed `btn-success` (green) → `btn-primary` on next-topic buttons in dashboard and topic page
- Semantic colors (green/amber/red) now exclusively on dots and state banners

### P1 — Dashboard CTA hierarchy
- "Weiter lernen →" made full-width (`btn-block`)
- Practice card "Üben →" demoted to `btn-secondary` (gray)
- Files: `dashboard.html`, `style.css`

### P2 — Materials open by default
- Already implemented (`open` attribute on `<details>` in `klasse.html`)
- No change needed

### P3 — Quiz gating: explain the block
- Added "Du kannst das Quiz beliebig oft wiederholen." to subtask quiz card
- Added same note to topic quiz card
- Added "Du kannst das Quiz beliebig oft wiederholen — kein Druck." to `quiz.html` intro card
- Files: `klasse.html`, `quiz.html`

### P4 — Progress dot legend
- Added `TODO(human)` in `klasse.html` below dot row
- Pending: human contribution for legend HTML
- Files: `klasse.html`

### P5 — Quiz anxiety: "retrying is free"
- `quiz_result.html` (failed): Added "Du kannst es so oft versuchen, wie du möchtest…"
- `warmup.html`: Changed subtitle to "Kein Druck — das hier wird nicht bewertet und zählt nicht als Note."
- Files: `quiz_result.html`, `warmup.html`

### P6 — Easy Reading Mode: surface to right students
- Added subtle passive link at bottom of dashboard: "Schwer zu lesen? Lesemodus aktivieren →"
- Files: `dashboard.html`

### P7 — Post-quiz navigation
- Primary CTAs on `quiz_result.html` changed to `btn-primary btn-block btn-lg`
- Secondary actions stay inline/smaller
- Files: `quiz_result.html`, `style.css`

---

## Content Fixes Required (Teacher Side — MBI repo)

These are A-level problems but require authoring changes, not code:

1. **Task description quality** — shorter sentences, grade 5/6 vocabulary, no jargon
   - Rule added to `docs/shared/mbi/content-design.md`

2. **"Fertig wenn" measurability** — must be student-verifiable criterion
   - Rule added to `docs/shared/mbi/conventions.md`

---

## Design Principle Added

"Klarheit statt Features" added to `docs/shared/lernmanager/pedagogical.md`:
> Every change must add clarity, reduce clutter, or remove elements that can be taken away without breaking or limiting the app.

---

## Walkthrough Checklist (after code fixes)

Use `list_students.py` to find test accounts, then verify:

1. [ ] Dashboard: Is "Weiter lernen →" the obvious first action? (full-width, blue)
2. [ ] Dashboard: Is practice card clearly secondary? (gray, smaller)
3. [ ] Dashboard: Is reading mode hint visible but subtle?
4. [ ] Topic page: Does the dot legend decode the row?
5. [ ] Topic page: Do quiz cards show retry-is-free message?
6. [ ] Quiz: Is retry note shown before submission?
7. [ ] Quiz result (failed): Is retry-free message reassuring?
8. [ ] Quiz result (passed): Does the full-width CTA lead without hesitation?
9. [ ] Warmup: Does "nicht bewertet" message reduce anxiety?
