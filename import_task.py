#!/usr/bin/env python3
"""
Task Import Script for Lernmanager

Import task definitions from JSON files into the database.

Usage:
    python import_task.py <task_definition.json>
    python import_task.py --dry-run <task_definition.json>
    python import_task.py --batch task_definitions/
    python import_task.py --list
"""

import argparse
import json
import sys
from pathlib import Path

import config
import models


class ValidationError(Exception):
    """Raised when task validation fails."""
    pass


def load_task_json(filepath):
    """Load and parse task definition JSON."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}")

    return data


def _validate_quiz(quiz, prefix="Quiz"):
    """Validate quiz JSON structure. Returns list of error strings."""
    errors = []
    if 'questions' not in quiz:
        errors.append(f"{prefix} missing 'questions' array")
    elif not isinstance(quiz['questions'], list):
        errors.append(f"{prefix} questions must be a list")
    else:
        for i, q in enumerate(quiz['questions']):
            label = f"{prefix} question {i+1}"
            if not isinstance(q, dict):
                errors.append(f"{label} must be an object")
                continue
            if 'text' not in q or not q['text']:
                errors.append(f"{label} missing 'text'")

            qtype = q.get('type', 'multiple_choice')
            if qtype == 'fill_blank':
                if 'answers' not in q or not isinstance(q['answers'], list) or not q['answers']:
                    errors.append(f"{label} (fill_blank) missing or empty 'answers' list")
            elif qtype == 'short_answer':
                if 'rubric' not in q or not q['rubric']:
                    errors.append(f"{label} (short_answer) missing 'rubric'")
            elif qtype == 'multiple_choice':
                if 'options' not in q or not isinstance(q['options'], list):
                    errors.append(f"{label} missing or invalid 'options'")
                elif len(q['options']) < 2:
                    errors.append(f"{label} needs at least 2 options")
                if 'correct' not in q or not isinstance(q['correct'], list):
                    errors.append(f"{label} missing or invalid 'correct'")
                elif 'options' in q and isinstance(q['options'], list):
                    for idx in q.get('correct', []):
                        if not isinstance(idx, int) or idx < 0 or idx >= len(q['options']):
                            errors.append(f"{label} has invalid correct index: {idx}")
            else:
                errors.append(f"{label} has unknown type '{qtype}'")
    return errors


def validate_task_structure(data):
    """Validate required fields are present and valid."""
    errors = []

    if 'task' not in data:
        raise ValidationError("Missing 'task' root element")

    task = data['task']

    # Required fields
    required = ['name', 'beschreibung', 'fach', 'stufe']
    for field in required:
        if field not in task or not task[field]:
            errors.append(f"Missing required field: {field}")

    # Validate fach
    if 'fach' in task and task['fach'] not in config.SUBJECTS:
        errors.append(f"Invalid fach '{task['fach']}'. Must be one of: {', '.join(config.SUBJECTS)}")

    # Validate stufe
    if 'stufe' in task and task['stufe'] not in config.LEVELS:
        errors.append(f"Invalid stufe '{task['stufe']}'. Must be one of: {', '.join(config.LEVELS)}")

    # Validate kategorie if provided
    if 'kategorie' in task and task['kategorie'] not in ['pflicht', 'bonus']:
        errors.append("Invalid kategorie. Must be 'pflicht' or 'bonus'")

    # Validate voraussetzungen (prerequisites)
    if 'voraussetzungen' in task:
        if not isinstance(task['voraussetzungen'], list):
            errors.append("voraussetzungen must be a list of task names")
        else:
            for i, v in enumerate(task['voraussetzungen']):
                if not isinstance(v, str) or not v:
                    errors.append(f"Voraussetzung {i+1} must be a non-empty string")

    # Validate subtasks
    VALID_PATHS = ('wanderweg', 'bergweg', 'gipfeltour')
    VALID_PATH_MODELS = ('skip', 'depth')
    if 'subtasks' in task:
        if not isinstance(task['subtasks'], list):
            errors.append("subtasks must be a list")
        else:
            for i, sub in enumerate(task['subtasks']):
                if not isinstance(sub, dict):
                    errors.append(f"Subtask {i+1} must be an object")
                    continue
                if 'beschreibung' not in sub or not sub['beschreibung']:
                    errors.append(f"Subtask {i+1} missing 'beschreibung'")
                # path is required
                if 'path' not in sub or sub['path'] not in VALID_PATHS:
                    errors.append(f"Subtask {i+1} missing or invalid 'path'. Must be one of: {', '.join(VALID_PATHS)}")
                # path_model is optional, defaults to 'skip'
                if 'path_model' in sub and sub['path_model'] not in VALID_PATH_MODELS:
                    errors.append(f"Subtask {i+1} invalid 'path_model'. Must be one of: {', '.join(VALID_PATH_MODELS)}")
                # graded_artifact is optional
                if 'graded_artifact' in sub and sub['graded_artifact']:
                    ga = sub['graded_artifact']
                    if not isinstance(ga, dict):
                        errors.append(f"Subtask {i+1} graded_artifact must be an object")
                    else:
                        if 'keyword' not in ga or not ga['keyword']:
                            errors.append(f"Subtask {i+1} graded_artifact missing 'keyword'")
                        if 'format' not in ga or not ga['format']:
                            errors.append(f"Subtask {i+1} graded_artifact missing 'format'")
                if 'quiz' in sub and sub['quiz']:
                    errors.extend(_validate_quiz(sub['quiz'], f"Subtask {i+1} quiz"))

    # Validate materials
    if 'materials' in task:
        if not isinstance(task['materials'], list):
            errors.append("materials must be a list")
        else:
            for i, mat in enumerate(task['materials']):
                if not isinstance(mat, dict):
                    errors.append(f"Material {i+1} must be an object")
                elif 'typ' not in mat:
                    errors.append(f"Material {i+1} missing 'typ'")
                elif mat['typ'] not in ['link', 'datei']:
                    errors.append(f"Material {i+1} has invalid typ '{mat['typ']}'. Must be 'link' or 'datei'")
                if 'pfad' not in mat or not mat['pfad']:
                    errors.append(f"Material {i+1} missing 'pfad'")

    # Validate topic-level quiz
    if 'quiz' in task and task['quiz']:
        errors.extend(_validate_quiz(task['quiz'], "Topic quiz"))

    if errors:
        raise ValidationError("\n".join(errors))

    return True


def check_duplicate(task_data, warnings=None):
    """Check if a task with the same name, fach, and stufe already exists.
    Returns existing task ID if duplicate found, None otherwise.
    If warnings list provided, appends warning message instead of printing."""
    task = task_data['task']
    existing_tasks = models.get_all_tasks()

    for existing in existing_tasks:
        if (existing['name'] == task['name'] and
            existing['fach'] == task['fach'] and
            existing['stufe'] == task['stufe']):
            msg = f"Thema '{task['name']}' ({task['fach']} {task['stufe']}) existiert bereits (ID: {existing['id']})"
            if warnings is not None:
                warnings.append(msg)
            return existing['id']

    return None


def import_task(task_data, dry_run=False, warnings=None):
    """Import a task into the database.
    If warnings list provided, appends warning messages instead of printing."""
    task = task_data['task']

    # Check for duplicates
    existing_id = check_duplicate(task_data, warnings=warnings)
    if existing_id:
        if warnings is None:
            print(f"Warning: Task '{task['name']}' ({task['fach']} {task['stufe']}) already exists (ID: {existing_id})")
        return None

    if dry_run:
        print("\n[DRY RUN] Would import:")
        print(f"  Task: {task['name']}")
        print(f"  Fach: {task['fach']}, Stufe: {task['stufe']}")
        print(f"  Kategorie: {task.get('kategorie', 'pflicht')}")
        if task.get('number'):
            print(f"  Nummer: {task['number']}")
        if task.get('why_learn_this'):
            print(f"  Warum: {task['why_learn_this'][:50]}...")
        if task.get('lernziel'):
            print(f"  Lernziel: {task['lernziel'][:50]}...")
        if task.get('voraussetzungen'):
            print(f"  Voraussetzungen: {', '.join(task['voraussetzungen'])}")
        subtasks = task.get('subtasks', [])
        subtasks_with_quiz = sum(1 for s in subtasks if s.get('quiz'))
        print(f"  Subtasks: {len(subtasks)} ({subtasks_with_quiz} with quiz)")
        print(f"  Subtask quiz required: {task.get('subtask_quiz_required', True)}")
        print(f"  Materials: {len(task.get('materials', []))}")
        if task.get('quiz'):
            print(f"  Topic quiz questions: {len(task['quiz'].get('questions', []))}")
        return None

    # Prepare quiz JSON
    quiz_json = None
    if task.get('quiz') and task['quiz'].get('questions'):
        quiz_json = json.dumps(task['quiz'], ensure_ascii=False)

    # Create task
    task_id = models.create_task(
        name=task['name'],
        beschreibung=task['beschreibung'],
        lernziel=task.get('lernziel', ''),
        fach=task['fach'],
        stufe=task['stufe'],
        kategorie=task.get('kategorie', 'pflicht'),
        quiz_json=quiz_json,
        number=task.get('number', 0),
        why_learn_this=task.get('why_learn_this'),
        lernziel_schueler=task.get('lernziel_schueler')
    )

    # Handle prerequisites (by name lookup)
    voraussetzungen = task.get('voraussetzungen', [])
    if voraussetzungen:
        all_tasks = models.get_all_tasks()
        task_name_to_id = {t['name']: t['id'] for t in all_tasks}
        for v_name in voraussetzungen:
            if v_name in task_name_to_id:
                models.add_task_voraussetzung(task_id, task_name_to_id[v_name])
            else:
                msg = f"Voraussetzung '{v_name}' nicht gefunden, übersprungen"
                if warnings is not None:
                    warnings.append(msg)
                else:
                    print(f"  Warning: {msg}")

    # Set subtask_quiz_required if specified (default is 1/true in DB)
    if 'subtask_quiz_required' in task:
        models.update_task(task_id, task['name'], task['beschreibung'],
                          task.get('lernziel', ''), task['fach'], task['stufe'],
                          task.get('kategorie', 'pflicht'), quiz_json,
                          task.get('number', 0), task.get('why_learn_this'),
                          subtask_quiz_required=1 if task['subtask_quiz_required'] else 0,
                          lernziel_schueler=task.get('lernziel_schueler'))

    # Create subtasks and track position -> ID mapping
    subtasks = task.get('subtasks', [])
    subtask_id_by_position = {}
    for i, sub in enumerate(subtasks):
        reihenfolge = sub.get('reihenfolge', i)
        estimated_minutes = sub.get('estimated_minutes')
        sub_quiz_json = json.dumps(sub['quiz'], ensure_ascii=False) if sub.get('quiz') else None
        path = sub.get('path')
        path_model = sub.get('path_model', 'skip')
        graded_artifact_json = json.dumps(sub['graded_artifact'], ensure_ascii=False) if sub.get('graded_artifact') else None
        sub_id = models.create_subtask(task_id, sub['beschreibung'], reihenfolge, estimated_minutes, sub_quiz_json,
                                       path=path, path_model=path_model, graded_artifact_json=graded_artifact_json)
        subtask_id_by_position[reihenfolge] = sub_id

    # Create materials and restore subtask assignments
    materials = task.get('materials', [])
    for mat in materials:
        mat_id = models.create_material(
            task_id,
            mat['typ'],
            mat['pfad'],
            mat.get('beschreibung', '')
        )
        # Restore per-Aufgabe assignments if present
        if mat.get('subtask_indices'):
            assigned_ids = [
                subtask_id_by_position[pos]
                for pos in mat['subtask_indices']
                if pos in subtask_id_by_position
            ]
            if assigned_ids:
                models.set_material_subtask_assignments(mat_id, assigned_ids)

    return task_id


def import_batch(directory, dry_run=False):
    """Import all task JSON files from a directory."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    json_files = sorted(dir_path.glob("*.json"))
    # Exclude schema files
    json_files = [f for f in json_files if not f.name.endswith('_schema.json')]

    if not json_files:
        print(f"No JSON files found in {directory}")
        return []

    print(f"Found {len(json_files)} task file(s) in {directory}\n")

    results = {"imported": [], "skipped": [], "failed": []}

    for filepath in json_files:
        print(f"--- {filepath.name} ---")
        try:
            data = load_task_json(filepath)
            validate_task_structure(data)
            task_id = import_task(data, dry_run=dry_run)

            if task_id:
                results["imported"].append((filepath.name, task_id))
                print(f"Imported: {data['task']['name']} (ID: {task_id})")
            else:
                results["skipped"].append(filepath.name)
        except (ValidationError, FileNotFoundError) as e:
            results["failed"].append((filepath.name, str(e)))
            print(f"Failed: {e}")
        print()

    # Summary
    print("\n=== BATCH IMPORT SUMMARY ===")
    if dry_run:
        print("[DRY RUN - no changes made]")
    print(f"Imported: {len(results['imported'])}")
    print(f"Skipped:  {len(results['skipped'])} (duplicates)")
    print(f"Failed:   {len(results['failed'])}")

    if results["failed"]:
        print("\nFailed files:")
        for name, error in results["failed"]:
            print(f"  - {name}: {error[:60]}...")

    return results


def list_tasks():
    """List all existing tasks."""
    tasks = models.get_all_tasks()

    if not tasks:
        print("No tasks in database.")
        return

    print(f"\nExisting tasks ({len(tasks)}):\n")
    print(f"{'ID':<4} {'Name':<40} {'Fach':<12} {'Stufe':<8} {'Kategorie':<10}")
    print("-" * 80)

    for t in tasks:
        name = t['name'][:38] + '..' if len(t['name']) > 40 else t['name']
        print(f"{t['id']:<4} {name:<40} {t['fach']:<12} {t['stufe']:<8} {t['kategorie']:<10}")


def main():
    parser = argparse.ArgumentParser(
        description='Import task definitions into Lernmanager database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python import_task.py task_definitions/task_01.json
  python import_task.py --dry-run task_definitions/task_01.json
  python import_task.py --batch task_definitions/
  python import_task.py --batch task_definitions/ --dry-run
  python import_task.py --list
        '''
    )
    parser.add_argument('file', nargs='?', help='JSON file to import')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate and show what would be imported without making changes')
    parser.add_argument('--batch', metavar='DIR',
                        help='Import all JSON files from a directory')
    parser.add_argument('--list', action='store_true',
                        help='List all existing tasks in the database')

    args = parser.parse_args()

    # Initialize database if needed
    models.init_db()

    if args.list:
        list_tasks()
        return 0

    if args.batch:
        try:
            results = import_batch(args.batch, dry_run=args.dry_run)
            return 0 if not results["failed"] else 1
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    if not args.file:
        parser.print_help()
        return 1

    try:
        # Load JSON
        print(f"Loading: {args.file}")
        data = load_task_json(args.file)

        # Support bulk export format: {"tasks": [...]}
        if 'tasks' in data and isinstance(data['tasks'], list):
            print(f"Bulk format detected: {len(data['tasks'])} tasks\n")
            results = {"imported": [], "skipped": [], "failed": []}
            for task_data in data['tasks']:
                wrapped = {'task': task_data}
                try:
                    validate_task_structure(wrapped)
                    task_id = import_task(wrapped, dry_run=args.dry_run)
                    if task_id:
                        results["imported"].append((task_data['name'], task_id))
                        print(f"  Imported: {task_data['name']} (ID: {task_id})")
                    else:
                        results["skipped"].append(task_data['name'])
                        if not args.dry_run:
                            print(f"  Skipped: {task_data['name']}")
                except ValidationError as e:
                    results["failed"].append((task_data.get('name', '?'), str(e)))
                    print(f"  Failed: {task_data.get('name', '?')}: {e}")
            print(f"\nImported: {len(results['imported'])}, Skipped: {len(results['skipped'])}, Failed: {len(results['failed'])}")
            return 0 if not results["failed"] else 1

        # Single task format: {"task": {...}}
        print("Validating structure...")
        validate_task_structure(data)
        print("Validation passed!")

        # Import
        task_id = import_task(data, dry_run=args.dry_run)

        if task_id:
            task = data['task']
            print(f"\nSuccessfully imported task:")
            print(f"  ID: {task_id}")
            print(f"  Name: {task['name']}")
            print(f"  Fach: {task['fach']}")
            print(f"  Stufe: {task['stufe']}")
            if task.get('voraussetzungen'):
                print(f"  Voraussetzungen: {len(task['voraussetzungen'])}")
            print(f"  Subtasks: {len(task.get('subtasks', []))}")
            print(f"  Materials: {len(task.get('materials', []))}")
            if task.get('quiz'):
                print(f"  Quiz questions: {len(task['quiz'].get('questions', []))}")
        elif not args.dry_run:
            print("\nImport skipped (duplicate or error).")

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"Validation error:\n{e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
