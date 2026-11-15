"""subtask.content_changed_at: set only when an Aufgabe's content really changes
(migrate_081). Updates keep ticks by position, so this date is what tells a tick
on the old content apart."""
import json

import models


def _topic():
    task_id = models.create_task('5 - Test', 'x', '', 'MBI', '5', 'pflicht')
    models.create_subtask(task_id, '### Eins', reihenfolge=0,
                          quiz_json=json.dumps({'questions': [{'text': 'a', 'options': ['x'], 'correct': [0]}]}))
    models.create_subtask(task_id, '### Zwei', reihenfolge=1)
    return task_id


def _changed(task_id):
    return [s['content_changed_at'] for s in models.get_subtasks(task_id)]


def test_unchanged_save_keeps_null(db):
    task_id = _topic()
    subs = models.get_subtasks(task_id)
    # same content, quiz reformatted and description with trailing whitespace
    quiz = json.dumps(json.loads(subs[0]['quiz_json']), indent=2)
    models.update_subtasks(task_id, ['### Eins  ', '### Zwei'], quiz_json_list=[quiz, ''])
    assert _changed(task_id) == [None, None]


def test_changed_description_sets_date_only_there(db):
    task_id = _topic()
    subs = models.get_subtasks(task_id)
    models.update_subtasks(task_id, ['### Eins', '### Zwei neu'], quiz_json_list=[subs[0]['quiz_json'], ''])
    first, second = _changed(task_id)
    assert first is None and second is not None


def test_insert_in_middle_marks_shifted_positions(db):
    task_id = _topic()
    subs = models.get_subtasks(task_id)
    models.update_subtasks_from_import(task_id, [
        {'beschreibung': '### Eins', 'reihenfolge': 0, 'quiz': json.loads(subs[0]['quiz_json'])},
        {'beschreibung': '### Neu', 'reihenfolge': 1},
        {'beschreibung': '### Zwei', 'reihenfolge': 2},
    ])
    changed = _changed(task_id)
    assert changed[0] is None
    assert changed[1] is not None   # old "Zwei" row now holds "Neu": ticks there are stale
    assert changed[2] is None        # new row, nobody has ticked it
