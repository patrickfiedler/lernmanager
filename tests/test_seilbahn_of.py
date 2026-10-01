"""`seilbahn_of`: a Seilbahn twin names the regular topic it belongs to.

MBI request 2026-08-31, decided 2026-10-01: two topics, linked by the regular
topic's unit_slug on the twin. This step only stores and exports the link.
"""
import pytest

import import_task
import models


def _data(paths=('seilbahn', 'seilbahn'), **task_overrides):
    task = {
        'name': '2 - Mein digitaler Alltag', 'beschreibung': 'x', 'lernziel': '', 'fach': 'MBI',
        'stufe': '6', 'kategorie': 'pflicht', 'unit_slug': 'seilbahn_kl6_digitaler_alltag',
        'seilbahn_of': 'kl6_digitaler_alltag',
        'subtasks': [{'beschreibung': f'### Aufgabe {i}', 'reihenfolge': i, 'path': p}
                     for i, p in enumerate(paths, 1)],
    }
    task.update(task_overrides)
    return {'task': task}


def _errors(data):
    with pytest.raises(import_task.ValidationError) as e:
        import_task.validate_task_structure(data)
    return str(e.value)


def test_import_export_round_trip(db):
    task_id = import_task.import_task(_data())
    assert models.get_task(task_id)['seilbahn_of'] == 'kl6_digitaler_alltag'
    assert models.export_task_to_dict(task_id)['seilbahn_of'] == 'kl6_digitaler_alltag'


def test_topic_without_the_key_stores_and_exports_nothing(db):
    data = _data(paths=('wanderweg',), unit_slug='kl6_digitaler_alltag')
    del data['task']['seilbahn_of']
    task_id = import_task.import_task(data)
    assert models.get_task(task_id)['seilbahn_of'] is None
    assert 'seilbahn_of' not in models.export_task_to_dict(task_id)


def test_reimport_updates_and_clears_the_link(db):
    task_id = import_task.import_task(_data())
    import_task.overwrite_task_from_import(task_id, _data(seilbahn_of='kl6_anderes_thema'))
    assert models.get_task(task_id)['seilbahn_of'] == 'kl6_anderes_thema'

    cleared = _data()
    del cleared['task']['seilbahn_of']
    import_task.overwrite_task_from_import(task_id, cleared)
    assert models.get_task(task_id)['seilbahn_of'] is None


def test_unresolved_target_is_a_warning_not_an_error(db):
    warnings = []
    assert import_task.validate_task_structure(_data(), warnings=warnings)
    assert any("unresolved unit_slug 'kl6_digitaler_alltag'" in w for w in warnings)


def test_resolved_target_gives_no_warning(db):
    models.create_task("2 - Mein digitaler Alltag", "", "", "MBI", "6", "", unit_slug='kl6_digitaler_alltag')
    warnings = []
    import_task.validate_task_structure(_data(), warnings=warnings)
    assert not any('seilbahn_of' in w for w in warnings)


def test_malformed_and_self_reference_are_rejected(db):
    assert "Invalid seilbahn_of" in _errors(_data(seilbahn_of='Kl6 Alltag'))
    assert "points to the topic itself" in _errors(_data(seilbahn_of='seilbahn_kl6_digitaler_alltag'))


def test_only_a_pure_seilbahn_topic_can_be_a_twin(db):
    assert "only a pure Seilbahn topic can be a twin" in _errors(_data(paths=('seilbahn', 'wanderweg')))
