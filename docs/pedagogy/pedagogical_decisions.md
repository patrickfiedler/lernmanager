# Pedagogical & Didactical Decisions

Core design decisions behind the Lernmanager, with rationale.

**Related:** Shared cross-project summaries at `docs/shared/lernmanager/pedagogical.md`. Content-side pedagogical decisions at `docs/shared/mbi/pedagogical.md`. LLM grading rationale at `docs/shared/grading-with-llm/pedagogical.md`.

## Teaching Philosophy

The Lernmanager is designed to **complement in-person teaching, not replace it.** The app handles deterministic decisions (who's next, what's their path, have they passed) so that the teacher's limited cognitive bandwidth goes to the work that actually requires a human: reading faces, sensing frustration, knowing when to push and when to back off.

**Core belief:** A classroom is a high-frequency decision environment. Trusting oneself to make the right call for every student every day is unrealistic. Clear self-running systems free the teacher to shine with personal support — both for struggling students who need help and for stronger students who benefit from conversations about perspectives and deeper understanding.

## Self-Paced Learning with Guardrails

Students work through topics at their own pace, but within a structured environment:

- **Topic queue** defines progression order (optional per class)
- **Per-task quizzes** verify understanding before moving on
- **Topic-level quizzes** verify overall comprehension
- **Structured task descriptions** (`Ziel`, `Aufgabe`, `Tipp`, `Fertig wenn`) ensure students know *why* they're doing something and *when they're done*

This is structured autonomy, not unguided self-study.

## Differentiated Learning Paths

Three cumulative difficulty paths: Wanderweg (foundational) ⊂ Bergweg (full curriculum) ⊂ Gipfeltour (everything).

**Key decision: bidirectional switching.** Students can move down as well as up. This trusts students to self-assess honestly rather than trapping them on a difficult track out of pride or teacher assignment.

**Key decision: all tasks visible.** Non-required tasks are styled as optional (dimmed), not hidden. Students see what exists beyond their current path, which supports curiosity and informed path decisions.

## Quiz Pass Threshold (70%)

Currently set at 70% for all quiz types. This is a **balance between momentum and frustration** — strict enough to catch major gaps, lenient enough to avoid blocking students who understand the core concepts but stumble on details.

### Open question

The 70% experience may differ by question type. Missing 30% of multiple-choice might mean shallow gaps. Missing 30% of fill-in-the-blank or short-answer (LLM-graded) might mean deeper conceptual problems. Per-question-type thresholds are a possible future refinement, pending observational data from actual teaching practice.

**Decision: wait for data.** This needs real classroom observation before adjusting, not theoretical optimization.

## Topic Queue: Optional by Design

The topic queue defines progression order per class but remains optional.

**Rationale:** Making it required would only remove ~4 guard clauses but would add setup overhead for simple classes, break per-student assignment overrides, and force migration of existing classes. The queue handles *progression*; manual assignment handles *exceptions*. Both are needed in practice.

## System Portability

The Lernmanager is designed to travel with the teacher, not stay with the school. It supports a specific teaching style (structured autonomy + personal support) and is maintained by one person. If the teacher changes schools, the system comes along; successors at the old school receive a handover but the app is not designed for institution-wide adoption.

## Known Tensions and Growth Edges

Identified through critical self-reflection (2026-02-15). These are not bugs to fix immediately but tensions to be aware of and evolve over time.

### Self-paced vs. self-directed

The current system is self-paced but not self-directed. Task descriptions are tightly scaffolded ("Öffne, Schreibe, Speichere") — appropriate for grades 5/6, but students rarely face genuine ambiguity or make real choices about *what* to create. The next evolution may include tasks with deliberate openness: student choice about what to make, not just how well to make it.

### Individual throughput vs. social learning

The system is designed around individual work. Self-paced progression inherently makes collaboration harder. But 10-12 year olds learn enormously from each other: explaining to peers, arguing about design choices, debugging together. The Lehrplan expects cross-cutting competencies (Kollaboration, Reflexion, Adressatengerecht). Possible response: 2-3 explicitly collaborative tasks per Kapitel, designed to work within the self-paced framework.

### Quizzes vs. discussions

Quizzes replaced unreliable whole-class discussions ("attention management"). This solved the engagement problem but also removed the space where students practice articulating ideas, disagreeing respectfully, and thinking on their feet — competencies that can't be quizzed. The question isn't whether quizzes are better than bad discussions, but whether the discussions can be improved rather than replaced entirely.

### LLM grading at this age

Automated feedback is fast and consistent. But for 10-year-olds, *who* gives feedback matters as much as *what* the feedback says. "Your teacher noticed X" hits differently than a system-generated response. LLM grading gains scalability at the cost of relational impact. Currently used for fill-in-the-blank and short-answer only — not for major artifacts.

### Scaffolding tightness over time

Tight scaffolding is defensible for grades 5/6. But if students stay in this system into grade 7+, the scaffolding should progressively loosen. This isn't implemented yet — the task format is uniform regardless of age or experience.

## Design Principles

These mirror the software principles but apply to the pedagogical design:

| Principle | Application |
|-----------|-------------|
| Automate the deterministic | System handles "who's next" and "did they pass" |
| Reserve humans for the human | Teacher focuses on support, motivation, conversation |
| Trust students with information | All paths visible, bidirectional switching, self-paced |
| Structure reduces anxiety | Clear goals, clear completion criteria, clear next steps |
| Wait for data | Don't optimize thresholds or flows without classroom evidence |
