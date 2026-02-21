# Lernmanager Documentation

This directory contains organized documentation for the Lernmanager project.

## Structure

### `/guides/` - User-Facing Documentation
Guides for deploying and maintaining Lernmanager:
- `MIGRATION_GUIDE.md` - Complete guide for migrating to new deployment system
- `MIGRATE_PRODUCTION.md` - Quick-start one-liner for production migration

See also:
- `deploy/QUICK_REFERENCE.md` - Quick reference for common operations
- `DEPLOYMENT_IMPROVEMENTS_SUMMARY.md` (root) - Overview of deployment system

### `/archive/` - Historical Documentation
Organized by date and topic, containing planning documents, research notes, and implementation tracking for completed work.

Each archive folder contains:
- `README.md` - Summary of the work
- Original planning and research documents
- Related commit references

#### Archive Topics

**2026-01-26**
- `deployment_improvements/` - EnvironmentFile secrets & auto-migrations
- `production_debugging/` - Production breakage investigation

**2026-01**
- `performance_optimization/` - Async logging, caching, WAL mode
- `caching_investigation/` - Template and bytecode caching research
- `logging_system/` - Admin-controlled logging toggle
- `student_redesign/` - Student interface improvements
- `unterricht_rewrite/` - Attendance/evaluation page redesign
- `class_assignment_bug/` - Bug fix for class-wide assignments
- `infrastructure_research/` - WSGI server comparison

### `/pedagogy/` - Teaching Philosophy
- `pedagogical_decisions.md` - Core teaching philosophy, design rationale, known tensions

### `/shared/` - Cross-Project Decisions (symlink → `~/coding/shared-decisions/`)
Shared decision documents across the Lernmanager ecosystem:
- `lernmanager/` — pedagogical, technical, and content convention decisions for this app
- `mbi/` — MBI curriculum content design (grades 5/6 Medienbildung & Informatik)
- `grading-with-llm/` — LLM-based automated artifact grading system

### Top-Level Documents

- `task_json_format.md` - Aufgabe/quiz JSON format specification
- `2026-02-13_lernmanager_curriculum_spec.md` - Curriculum structure and learning paths spec

## Navigation

**For pedagogical rationale:** See `pedagogy/pedagogical_decisions.md` and `shared/lernmanager/pedagogical.md`

**For cross-project decisions:** See `shared/README.md`

**For deployment and operations:** See `/guides/` and `deploy/QUICK_REFERENCE.md`

**For project history:** See `PROJECT_HISTORY.md` in root directory

**For current plans:** See `future_features_plan.md` and `student_redesign_roadmap.md` in root

**For archived work:** Browse `/archive/` by date or topic
