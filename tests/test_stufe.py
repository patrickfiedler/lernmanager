"""Grade levels are single integers since 2026-08-25 (config.LEVELS).

Legacy double-year values ('5/6') are rejected on import but still resolve to
both grades so existing DB rows keep matching and sorting sensibly.
"""
import config
import utils
from import_task import validate_task_structure, ValidationError
import pytest


def _task(stufe):
    return {"task": {"name": "X", "beschreibung": "x", "fach": "MBI", "stufe": stufe}}


def test_levels_are_single_grades():
    assert '5/6' not in config.LEVELS
    assert {'5', '6', '7'} <= set(config.LEVELS)


def test_import_accepts_single_grade():
    validate_task_structure(_task("6"))


def test_import_rejects_legacy_double_year():
    with pytest.raises(ValidationError) as exc:
        validate_task_structure(_task("5/6"))
    assert "Veraltete stufe" in str(exc.value)


def test_import_still_accepts_chemie_levels():
    validate_task_structure(_task("11s"))
    validate_task_structure(_task("11/12"))


def test_parse_stufen():
    assert utils.parse_stufen("6") == {6}
    assert utils.parse_stufen("5/6") == {5, 6}
    assert utils.parse_stufen("11s") == {11}
    assert utils.parse_stufen("11/12") == {11, 12}
    assert utils.parse_stufen("Seilbahn") == set()
    assert utils.parse_stufen(None) == set()


def test_stufe_sort_key_puts_numbers_first():
    values = ["Seilbahn", "10", "5", "11/12", "6"]
    assert sorted(values, key=utils.stufe_sort_key) == ["5", "6", "10", "11/12", "Seilbahn"]


def test_split_tasks_by_stufe_matches_legacy_pairs():
    tasks = [{"stufe": "5"}, {"stufe": "6"}, {"stufe": "5/6"}, {"stufe": "Seilbahn"}]
    exact, others = utils.split_tasks_by_stufe(tasks, [6])
    assert exact == [{"stufe": "6"}, {"stufe": "5/6"}]
    assert others == [{"stufe": "5"}, {"stufe": "Seilbahn"}]


def test_split_tasks_by_stufe_without_klassenstufe_does_not_split():
    tasks = [{"stufe": "5"}, {"stufe": "6"}]
    exact, others = utils.split_tasks_by_stufe(tasks, [None])
    assert exact == []
    assert others == tasks
