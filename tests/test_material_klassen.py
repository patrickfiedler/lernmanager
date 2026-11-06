"""Material visible only to some classes.

MBI request 2026-11-06 (Kl.7 Unit 3): each Lerngruppe collects data in its own
Etherpad. `klassen` on a material names the classes that see it; the importer
stores their ids. Unknown or ambiguous name = import error (Patrick 2026-11-06),
because a wrong guess would put a group's rows in another group's pad.
"""
import pytest

import import_task
import models

PADS = {'7a': 'https://pad.example/7a', '7b': 'https://pad.example/7b'}


def _data():
    return {'task': {
        'name': 'Tabellen', 'beschreibung': 'Schulweg', 'lernziel': '', 'fach': 'MBI',
        'stufe': '7', 'kategorie': 'pflicht',
        'subtasks': [{'beschreibung': '### Daten\n\n1. Trag dich ein.', 'reihenfolge': 1,
                      'path': 'wanderweg'}],
        'materials': [{'typ': 'link', 'pfad': url, 'beschreibung': f'Pad {name}',
                       'klassen': [name], 'subtask_indices': [1]}
                      for name, url in PADS.items()]
                     + [{'typ': 'link', 'pfad': 'https://example.org/alle', 'beschreibung': 'Für alle'}],
    }}


def _errors(data):
    with pytest.raises(import_task.ValidationError) as e:
        import_task.validate_task_structure(data)
    return str(e.value)


def _setup():
    klassen = {name: models.create_klasse(name) for name in PADS}
    task_id = import_task.import_task(_data())
    return klassen, task_id


def test_unknown_class_name_is_an_import_error(db):
    models.create_klasse('7a')
    assert "Klasse '7b' nicht gefunden" in _errors(_data())


def test_empty_list_is_an_import_error(db):
    data = _data()
    data['task']['materials'][0]['klassen'] = []
    assert 'nicht-leere Liste' in _errors(data)


def test_queries_filter_by_class_admin_sees_all(db):
    klassen, task_id = _setup()
    subtask_id = models.get_subtasks(task_id)[0]['id']

    def pfade(materials):
        return sorted(m['pfad'] for m in materials)

    assert len(models.get_materials(task_id)) == 3
    for name, url in PADS.items():
        expected = sorted([url, 'https://example.org/alle'])
        assert pfade(models.get_materials(task_id, klassen[name])) == expected
        assert pfade(models.get_materials_for_subtask(task_id, subtask_id, klassen[name])) == expected


def test_export_round_trip_uses_names(db):
    _, task_id = _setup()
    exported = {m['pfad']: m.get('klassen') for m in models.export_task_to_dict(task_id)['materials']}
    assert exported == {PADS['7a']: ['7a'], PADS['7b']: ['7b'], 'https://example.org/alle': None}


def test_student_page_shows_only_own_pad(app, client):
    klassen, task_id = _setup()
    sid = models.create_student('N', 'V', 'user7a', 'pw')
    models.add_student_to_klasse(sid, klassen['7a'])
    models.assign_task_to_student(sid, klassen['7a'], task_id)
    with client.session_transaction() as sess:
        sess['student_id'] = sid

    for url in ('/schueler/thema/tabellen', '/schueler/thema/tabellen/drucken',
                '/schueler/thema/tabellen/aufgabe-1/drucken'):
        html = client.get(url).get_data(as_text=True)
        assert PADS['7a'] in html, url
        assert PADS['7b'] not in html, url


def test_admin_topic_page_names_the_classes(app, as_admin):
    _, task_id = _setup()
    html = as_admin.get(f'/admin/thema/{task_id}').get_data(as_text=True)
    assert 'nur: 7a' in html and 'nur: 7b' in html
