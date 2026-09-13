"""Import checks for per-question checkpoint hints and the `zweiwertig` flag
(relay "Tipps je Frage", 2026-09-13). Both are stored inside quiz_json as-is, so a
malformed value or a misspelled key must be caught at import, not discovered later.
"""
import json

import pytest

import models
from import_task import ValidationError, import_task, validate_task_structure


def _checkpoint(questions):
    return {
        "task": {
            "name": "12 - Testmodul",
            "beschreibung": "x",
            "fach": "MBI",
            "stufe": "5",
            "subtasks": [{
                "beschreibung": "### 12.9 - Checkpoint",
                "path": "wanderweg",
                "checkpoint_type": "quiz",
                "kern_standard_tag": "kern",
                "quiz": {"questions": questions},
            }],
        }
    }


def _short_answer(**extra):
    return {"type": "short_answer", "text": "Begründe.", "rubric": "Kern.", **extra}


def test_valid_hints_and_flag_import_and_survive_in_quiz_json(db):
    data = _checkpoint([
        _short_answer(hints=["Zähl die Ladungen.", "Was gleicht aus?"], zweiwertig=True),
        {"text": "Welche?", "options": ["a", "b"], "correct": [0], "hints": ["Lies nochmal."]},
    ])
    warnings = []
    validate_task_structure(data, warnings)
    assert warnings == []

    task_id = import_task(data)
    stored = json.loads(models.get_subtasks(task_id)[0]['quiz_json'])['questions']
    assert stored[0]['hints'] == ["Zähl die Ladungen.", "Was gleicht aus?"]
    assert stored[0]['zweiwertig'] is True


@pytest.mark.parametrize("hints", [
    "Zähl die Ladungen.",            # a string, not a list
    [],                              # empty list
    ["a", "b", "c", "d"],            # more than three
    ["Zähl die Ladungen.", "  "],    # blank entry
    [1, 2],                          # not strings
])
def test_malformed_hints_are_a_hard_error(hints):
    with pytest.raises(ValidationError, match="'hints'"):
        validate_task_structure(_checkpoint([_short_answer(hints=hints)]))


def test_zweiwertig_must_be_boolean():
    with pytest.raises(ValidationError, match="true or false"):
        validate_task_structure(_checkpoint([_short_answer(zweiwertig="ja")]))


def test_zweiwertig_only_on_short_answer():
    question = {"type": "matching", "text": "Ordne zu.", "pairs": [["a", "b"], ["c", "d"]],
                "zweiwertig": True}
    with pytest.raises(ValidationError, match="only applies to short_answer"):
        validate_task_structure(_checkpoint([question]))


def test_misspelled_key_warns_but_imports():
    warnings = []
    validate_task_structure(_checkpoint([_short_answer(zweiwertg=True, tipps=["x"])]), warnings)
    assert len(warnings) == 2
    assert all("did you mean" in w for w in warnings)
