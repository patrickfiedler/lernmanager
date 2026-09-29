"""Material variants: each student works on one combination from a pool.

MBI request 2026-09-24 (Kl.7 Unit 3): the topic lists allowed combinations,
Lernmanager hands each student one, balanced per class, and fills {key.N}
in the task text with the material's label. Decisions (Patrick 2026-09-29):
text comes from a `label` field, assignment happens on first opening.
"""
import copy
import json

import pytest

import import_task
import models

SETS = [['bild_a.jpg', 'bild_c.jpg'], ['bild_b.jpg', 'bild_d.jpg']]


def _data(**task_overrides):
    task = {
        'name': 'KI und Recherche', 'beschreibung': 'Bilder prüfen', 'lernziel': '', 'fach': 'MBI',
        'stufe': '7', 'kategorie': 'pflicht',
        'subtasks': [{'beschreibung': '### Fall\n\n1. Lade {fall.1} herunter.',
                      'fertig_wenn': '{fall.2} ist geprüft.', 'reihenfolge': 1, 'path': 'wanderweg'}],
        'materials': [{'typ': 'datei', 'pfad': f, 'beschreibung': f'Bild {f[5].upper()} – Beispiel',
                       'label': f'Bild {f[5].upper()}'}
                      for f in ['bild_a.jpg', 'bild_b.jpg', 'bild_c.jpg', 'bild_d.jpg']],
        'material_variants': [{'key': 'fall', 'assignment': 'balanced', 'sets': SETS}],
    }
    task.update(task_overrides)
    return {'task': task}


def _errors(data):
    with pytest.raises(import_task.ValidationError) as e:
        import_task.validate_task_structure(data)
    return str(e.value)


# ---------- import validation ----------

def test_valid_variants_pass(db):
    assert import_task.validate_task_structure(_data())


def test_placeholder_without_variants_is_rejected(db):
    assert "no material_variants entry 'fall'" in _errors(_data(material_variants=[]))


def test_placeholder_out_of_range_is_rejected(db):
    data = _data()
    data['task']['subtasks'][0]['tipps'] = 'Schau auf {fall.3}.'
    assert 'out of range' in _errors(data)


def test_material_in_a_set_needs_a_label(db):
    data = _data()
    del data['task']['materials'][0]['label']
    assert "'bild_a.jpg' needs a 'label'" in _errors(data)


def test_unknown_file_and_uneven_sets_are_rejected(db):
    data = _data(material_variants=[{'key': 'fall', 'sets': [['bild_a.jpg', 'fehlt.jpg'], ['bild_b.jpg']]}])
    msg = _errors(data)
    assert "'fehlt.jpg' is not a 'datei' material" in msg
    assert 'same length' in msg


def test_import_and_export_round_trip(db):
    task_id = import_task.import_task(_data())
    exported = models.export_task_to_dict(task_id)
    assert exported['material_variants'] == [{'key': 'fall', 'assignment': 'balanced', 'sets': SETS}]
    assert {m['pfad']: m['label'] for m in exported['materials']}['bild_c.jpg'] == 'Bild C'


# ---------- assignment ----------

def _class_with_students(task_id, n):
    klasse_id = models.create_klasse('7a')
    ids = []
    for i in range(n):
        sid = models.create_student(f'N{i}', f'V{i}', f'user{i}', 'pw')
        models.add_student_to_klasse(sid, klasse_id)
        models.assign_task_to_student(sid, klasse_id, task_id)
        ids.append(sid)
    return klasse_id, ids


def test_assignment_is_balanced_per_class_and_stable(db):
    task_id = import_task.import_task(_data())
    task = models.get_task(task_id)
    klasse_id, students = _class_with_students(task_id, 4)

    first = [models.assign_material_variants(s, klasse_id, task)['fall'] for s in students]
    assert sorted(map(tuple, first)) == sorted(map(tuple, SETS * 2))
    again = [models.assign_material_variants(s, klasse_id, task)['fall'] for s in students]
    assert again == first


def test_reimport_that_drops_a_set_reassigns_only_those_students(db):
    task_id = import_task.import_task(_data())
    klasse_id, students = _class_with_students(task_id, 2)
    before = {s: models.assign_material_variants(s, klasse_id, models.get_task(task_id))['fall'] for s in students}

    new_sets = [SETS[0], ['bild_d.jpg', 'bild_b.jpg']]
    import_task.overwrite_task_from_import(task_id, _data(material_variants=[{'key': 'fall', 'sets': new_sets}]))
    after = {s: models.assign_material_variants(s, klasse_id, models.get_task(task_id))['fall'] for s in students}

    for s in students:
        assert after[s] in new_sets
        if before[s] == SETS[0]:
            assert after[s] == SETS[0]


# ---------- student page and admin override ----------

def _login(client, student_id):
    with client.session_transaction() as sess:
        sess['student_id'] = student_id


def test_student_page_fills_placeholders_and_marks_materials(app, client):
    task_id = import_task.import_task(_data())
    klasse_id, (student_id,) = _class_with_students(task_id, 1)
    _login(client, student_id)

    html = client.get('/schueler/thema/ki-und-recherche').get_data(as_text=True)
    mine = models.assign_material_variants(student_id, klasse_id, models.get_task(task_id))['fall']
    first_label = 'Bild ' + mine[0][5].upper()
    assert '{fall.' not in html
    assert f'Lade {first_label} herunter.' in html
    assert 'für dich: Fall 1' in html


def test_admin_can_change_a_students_combination(app, as_admin):
    app.config['WTF_CSRF_ENABLED'] = False
    task_id = import_task.import_task(_data())
    klasse_id, (student_id,) = _class_with_students(task_id, 1)
    task = models.get_task(task_id)
    current = models.assign_material_variants(student_id, klasse_id, task)['fall']
    other = 1 - SETS.index(current)

    as_admin.post(f'/admin/schueler/{student_id}/material-variante',
                  data={'task_id': task_id, 'key': 'fall', 'set_index': other})

    assert models.assign_material_variants(student_id, klasse_id, task)['fall'] == SETS[other]
    page = as_admin.get(f'/admin/schueler/{student_id}').get_data(as_text=True)
    assert 'Material-Kombination' in page
