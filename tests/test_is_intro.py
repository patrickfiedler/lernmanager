"""Regression tests for is_intro import (lernmanager/todo.md: 'is_intro read on
import, exclude from progress count'). Field was authored by MBI content but
silently dropped on import until now - see docs/shared/lernmanager/task_json_format.md.
"""
import models
from import_task import import_task, validate_task_structure


def _task_data(subtasks):
    return {
        "task": {
            "name": "5 - Testthema",
            "beschreibung": "x",
            "fach": "MBI",
            "stufe": "5",
            "subtasks": subtasks,
        }
    }


def test_import_stores_is_intro_true(db):
    data = _task_data([
        {"beschreibung": "Einführung", "path": "wanderweg", "is_intro": True},
        {"beschreibung": "Aufgabe 1", "path": "wanderweg"},
    ])
    validate_task_structure(data)
    task_id = import_task(data)

    subtasks = models.get_subtasks(task_id)
    assert subtasks[0]['is_intro'] == 1
    assert subtasks[1]['is_intro'] == 0


def test_import_defaults_is_intro_false_when_absent(db):
    data = _task_data([{"beschreibung": "Aufgabe 1", "path": "wanderweg"}])
    validate_task_structure(data)
    task_id = import_task(data)

    subtasks = models.get_subtasks(task_id)
    assert subtasks[0]['is_intro'] == 0


def test_update_subtasks_from_import_preserves_is_intro(db):
    task_id = models.create_task("5 - Testthema", "x", "", "MBI", "5", "pflicht")
    models.create_subtask(task_id, "Einführung", 0, path="wanderweg")

    subtask_id_by_position = models.update_subtasks_from_import(task_id, [
        {"beschreibung": "Einführung", "reihenfolge": 0, "path": "wanderweg", "is_intro": True},
    ])

    updated = models.get_subtasks(task_id)
    assert updated[0]['id'] == subtask_id_by_position[0]  # in-place update, ID preserved
    assert updated[0]['is_intro'] == 1
