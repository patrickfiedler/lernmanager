"""Regression tests for Fork/Choice Artifact Model import validation and round-trip
(import_task.py, models.create_subtask/update_subtasks_from_import/export_task_to_dict).

Design: docs/shared/lernmanager/fork-choice-artifact-model.md decision 5.
"""
import models
import import_task


def _base_subtask(desc, **overrides):
    sub = {"beschreibung": desc, "path": "wanderweg"}
    sub.update(overrides)
    return sub


def test_import_rejects_fork_group_without_branch(db):
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "MBI", "stufe": "5",
                      "subtasks": [_base_subtask("A", fork_group="g1")]}}
    try:
        import_task.validate_task_structure(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "fork_group" in str(e) and "fork_branch" in str(e)


def test_import_rejects_single_branch_fork(db):
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "MBI", "stufe": "5",
                      "subtasks": [
                          _base_subtask("A", fork_group="g1", fork_branch="a", fork_branch_label="A"),
                      ]}}
    try:
        import_task.validate_task_structure(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "at least 2" in str(e)


def test_import_rejects_missing_branch_label(db):
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "MBI", "stufe": "5",
                      "subtasks": [
                          _base_subtask("A", fork_group="g1", fork_branch="a"),
                          _base_subtask("B", fork_group="g1", fork_branch="b", fork_branch_label="B"),
                      ]}}
    try:
        import_task.validate_task_structure(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "fork_branch_label" in str(e)


def test_import_rejects_noncontiguous_branch(db):
    data = {"task": {"name": "X", "beschreibung": "x", "fach": "MBI", "stufe": "5",
                      "subtasks": [
                          _base_subtask("A1", fork_group="g1", fork_branch="a", fork_branch_label="A"),
                          _base_subtask("B1", fork_group="g1", fork_branch="b", fork_branch_label="B"),
                          _base_subtask("A2", fork_group="g1", fork_branch="a"),
                      ]}}
    try:
        import_task.validate_task_structure(data)
        assert False, "should have raised"
    except import_task.ValidationError as e:
        assert "contiguous" in str(e)


def test_import_accepts_valid_fork_group(db):
    data = {"task": {"name": "Forkthema", "beschreibung": "x", "fach": "MBI", "stufe": "5",
                      "subtasks": [
                          _base_subtask("Basis"),
                          _base_subtask("A1", fork_group="g1", fork_branch="a", fork_branch_label="Weg A"),
                          _base_subtask("A2", fork_group="g1", fork_branch="a"),
                          _base_subtask("B1", fork_group="g1", fork_branch="b", fork_branch_label="Weg B",
                                        fork_branch_note="Ein Hinweis.", fork_required=False),
                      ]}}
    import_task.validate_task_structure(data)  # should not raise
    task_id = import_task.import_task(data)

    subtasks = models.get_subtasks(task_id)
    by_desc = {s["beschreibung"]: s for s in subtasks}
    assert by_desc["Basis"]["fork_group"] is None
    assert by_desc["A1"]["fork_group"] == "g1"
    assert by_desc["A1"]["fork_branch"] == "a"
    assert by_desc["A1"]["fork_branch_label"] == "Weg A"
    assert by_desc["B1"]["fork_branch_note"] == "Ein Hinweis."
    assert by_desc["B1"]["fork_required"] == 0
    assert by_desc["A1"]["fork_required"] == 1


def test_export_round_trip_preserves_fork_fields(db):
    task_id = models.create_task("Forkthema2", "x", "", "MBI", "5", "")
    models.create_subtask(task_id, "A1", reihenfolge=0,
                           fork_group="g1", fork_branch="a", fork_branch_label="Weg A",
                           fork_branch_note="Hinweis A", fork_required=1)

    exported = models.export_task_to_dict(task_id)
    sub = exported["subtasks"][0]
    assert sub["fork_group"] == "g1"
    assert sub["fork_branch"] == "a"
    assert sub["fork_branch_label"] == "Weg A"
    assert sub["fork_branch_note"] == "Hinweis A"
    assert sub["fork_required"] is True


def test_update_subtasks_from_import_persists_fork_fields(db):
    task_id = models.create_task("Forkthema3", "x", "", "MBI", "5", "")
    models.create_subtask(task_id, "A1", reihenfolge=0)

    models.update_subtasks_from_import(task_id, [
        {"beschreibung": "A1", "reihenfolge": 0, "path": "wanderweg",
         "fork_group": "g1", "fork_branch": "a", "fork_branch_label": "Weg A"},
    ])

    subtasks = models.get_subtasks(task_id)
    assert subtasks[0]["fork_group"] == "g1"
    assert subtasks[0]["fork_branch"] == "a"
