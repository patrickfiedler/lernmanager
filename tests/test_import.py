"""Tests for import_task duplicate detection."""
import models
from import_task import check_duplicate


def _make_task_data(name, fach, stufe, paths):
    """Build minimal task_data dict for check_duplicate."""
    return {
        "task": {
            "name": name,
            "fach": fach,
            "stufe": stufe,
            "subtasks": [{"path": p} for p in paths],
        }
    }


def _insert_topic_with_subtasks(name, fach, stufe, paths):
    """Create a topic in the DB with subtasks at given paths. Returns task_id."""
    task_id = models.create_task(name, "", "", fach, stufe, "pflicht")
    with models.db_session() as conn:
        for i, path in enumerate(paths):
            conn.execute(
                "INSERT INTO subtask (task_id, beschreibung, reihenfolge, path) VALUES (?, '', ?, ?)",
                (task_id, i, path),
            )
    return task_id


def test_duplicate_same_name_same_path_type_is_flagged(db):
    existing_id = _insert_topic_with_subtasks(
        "5 - Bots", "MBI", "5/6", ["wanderweg", "bergweg"]
    )
    data = _make_task_data("5 - Bots", "MBI", "5/6", ["wanderweg", "bergweg"])

    assert check_duplicate(data) == existing_id


def test_seilbahn_not_duplicate_of_regular_same_name(db):
    _insert_topic_with_subtasks("5 - Bots", "MBI", "5/6", ["wanderweg", "bergweg"])
    data = _make_task_data("5 - Bots", "MBI", "5/6", ["seilbahn", "seilbahn"])

    assert check_duplicate(data) is None


def test_regular_not_duplicate_of_seilbahn_same_name(db):
    _insert_topic_with_subtasks("5 - Bots", "MBI", "5/6", ["seilbahn", "seilbahn"])
    data = _make_task_data("5 - Bots", "MBI", "5/6", ["wanderweg", "bergweg"])

    assert check_duplicate(data) is None


def test_duplicate_seilbahn_vs_seilbahn_is_flagged(db):
    existing_id = _insert_topic_with_subtasks(
        "5 - Bots", "MBI", "5/6", ["seilbahn", "seilbahn"]
    )
    data = _make_task_data("5 - Bots", "MBI", "5/6", ["seilbahn", "seilbahn"])

    assert check_duplicate(data) == existing_id


def test_no_duplicate_different_fach(db):
    _insert_topic_with_subtasks("5 - Bots", "MBI", "5/6", ["wanderweg"])
    data = _make_task_data("5 - Bots", "Deutsch", "5/6", ["wanderweg"])

    assert check_duplicate(data) is None
