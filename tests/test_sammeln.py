"""Zeilen sammeln (MBI request 2026-11-11, Kl.7 Unit 3 Schulweg-Daten).

Aufgabe 1 collects one line per student, Aufgabe 2 lets the class download all
lines of its own class as .txt, without names, sorted, exactly as typed.
"""
import pytest

import import_task
import models

KOPF = 'Code;Minuten;km;Verkehrsmittel'


def _data():
    return {'task': {
        'name': 'Tabellen', 'beschreibung': 'Schulweg', 'lernziel': '', 'fach': 'MBI',
        'stufe': '7', 'kategorie': 'pflicht',
        'subtasks': [
            {'beschreibung': '### Eintragen', 'reihenfolge': 1, 'path': 'wanderweg',
             'sammeln': {'id': 'schulweg', 'hinweis': KOPF}},
            {'beschreibung': '### Auswerten', 'reihenfolge': 2, 'path': 'wanderweg',
             'sammeln_download': {'id': 'schulweg', 'dateiname': 'schulweg.txt', 'kopfzeile': KOPF}},
        ],
    }}


def _errors(data):
    with pytest.raises(import_task.ValidationError) as e:
        import_task.validate_task_structure(data)
    return str(e.value)


def _student(login, klasse_id, task_id, client=None):
    sid = models.create_student('N', login, login, 'pw')
    models.add_student_to_klasse(sid, klasse_id)
    models.assign_task_to_student(sid, klasse_id, task_id)
    return sid


@pytest.fixture(autouse=True)
def _no_csrf(request):
    if 'app' in request.fixturenames:
        request.getfixturevalue('app').config["WTF_CSRF_ENABLED"] = False


def _login(client, sid):
    with client.session_transaction() as sess:
        sess.clear()
        sess['student_id'] = sid


def test_download_id_without_collection_is_an_import_error(db):
    data = _data()
    data['task']['subtasks'][1]['sammeln_download']['id'] = 'schulwge'
    assert "id 'schulwge' wird in diesem Thema nirgends gesammelt" in _errors(data)


def test_unknown_field_and_bad_filename_are_import_errors(db):
    data = _data()
    data['task']['subtasks'][0]['sammeln']['platzhalter'] = 'x'
    data['task']['subtasks'][1]['sammeln_download']['dateiname'] = '../a.csv'
    errs = _errors(data)
    assert 'unbekannte Felder' in errs and 'dateiname muss auf .txt enden' in errs


def test_export_round_trip(db):
    task_id = import_task.import_task(_data())
    exported = models.export_task_to_dict(task_id)['subtasks']
    assert exported[0]['sammeln'] == _data()['task']['subtasks'][0]['sammeln']
    assert exported[1]['sammeln_download'] == _data()['task']['subtasks'][1]['sammeln_download']


def test_clean_keeps_text_exactly_but_one_line():
    assert models.clean_sammel_text('  A1 ; 12,5 Min ;3km; Fuß ') == '  A1 ; 12,5 Min ;3km; Fuß '
    assert models.clean_sammel_text('A1;12\r\nB2\t3\u2028x\x0by') == 'A1;12  B2 3 x y'
    assert models.clean_sammel_text('A1\x00;\x1b12') == 'A1;12'  # other control chars go
    assert len(models.clean_sammel_text('x' * 1000)) == models.SAMMEL_ZEILE_MAX
    assert not models.clean_sammel_text('\n\r\t')


def test_enter_change_download_own_class_only(app, client):
    k7a, k7b = models.create_klasse('7a'), models.create_klasse('7b')
    task_id = import_task.import_task(_data())
    anna = _student('anna', k7a, task_id)
    ben = _student('ben', k7a, task_id)
    carl = _student('carl', k7b, task_id)

    for sid, zeile in ((anna, 'Z9;10;2;Bus'), (ben, 'A1;5,5;1 km;Fuß'), (carl, 'B7;20;5;Rad')):
        _login(client, sid)
        client.post('/schueler/thema/tabellen/aufgabe/1/zeile', data={'zeile': zeile})
    _login(client, anna)
    client.post('/schueler/thema/tabellen/aufgabe/1/zeile', data={'zeile': 'Z9;12;2;Bus'})

    html = client.get('/schueler/thema/tabellen?aufgabe=1').get_data(as_text=True)
    assert 'Z9;12;2;Bus' in html and 'A1;5,5' not in html  # own line only

    resp = client.get('/schueler/thema/tabellen/aufgabe/2/sammlung.txt')
    assert resp.status_code == 200
    assert 'schulweg.txt' in resp.headers['Content-Disposition']
    body = resp.data
    assert body.startswith(b'\xef\xbb\xbf')  # BOM for Excel
    lines = body.decode('utf-8-sig').split('\r\n')
    assert lines[0] == KOPF and lines[-1] == ''
    assert sorted(lines[1:-1]) == ['A1;5,5;1 km;Fuß', 'Z9;12;2;Bus']
    assert client.get('/schueler/thema/tabellen/aufgabe/2/sammlung.txt').data == body  # stable per student

    # Aufgabe 1 has no download, Aufgabe 2 no collection
    assert client.get('/schueler/thema/tabellen/aufgabe/1/sammlung.txt').status_code == 404
    assert client.post('/schueler/thema/tabellen/aufgabe/2/zeile', data={'zeile': 'x'}).status_code == 404


def test_empty_line_deletes_own_entry(app, client):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    _login(client, sid)
    client.post('/schueler/thema/tabellen/aufgabe/1/zeile', data={'zeile': 'Z9;1'})
    client.post('/schueler/thema/tabellen/aufgabe/1/zeile', data={'zeile': ''})
    assert models.get_sammel_texte(k, 'schulweg') == []


def test_shuffle_differs_between_students_and_keeps_all_lines(db):
    k = models.create_klasse('7a')
    for i in range(20):
        sid = models.create_student('N', f's{i}', f's{i}', 'pw')
        models.set_sammel_zeile(k, 'schulweg', sid, f'Zeile {i:02d}')
    plain = models.get_sammel_texte(k, 'schulweg')
    a = models.get_sammel_texte(k, 'schulweg', shuffle_for=1)
    b = models.get_sammel_texte(k, 'schulweg', shuffle_for=2)
    assert sorted(a) == sorted(b) == plain
    assert a != b and a != plain


def test_rows_survive_reimport(db):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    models.set_sammel_zeile(k, 'schulweg', sid, 'Z9;1')
    import_task.import_task(_data())
    assert models.get_sammel_texte(k, 'schulweg') == ['Z9;1']


def test_teacher_sees_names_and_deletes_only_in_own_class(app, as_admin):
    k7a, k7b = models.create_klasse('7a'), models.create_klasse('7b')
    task_id = import_task.import_task(_data())
    anna = _student('anna', k7a, task_id)
    models.set_sammel_zeile(k7a, 'schulweg', anna, 'Unsinn')
    zeile_id = models.get_sammel_zeilen_for_klasse(k7a)['schulweg'][0]['id']

    html = as_admin.get(f'/admin/klasse/{k7a}').get_data(as_text=True)
    assert 'Unsinn' in html and 'anna' in html

    as_admin.post(f'/admin/klasse/{k7b}/sammel-zeile/{zeile_id}/loeschen')  # wrong class: nothing
    assert models.get_sammel_texte(k7a, 'schulweg') == ['Unsinn']
    as_admin.post(f'/admin/klasse/{k7a}/sammel-zeile/{zeile_id}/loeschen')
    assert models.get_sammel_texte(k7a, 'schulweg') == []


def test_deleting_student_deletes_their_line(db):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    models.set_sammel_zeile(k, 'schulweg', sid, 'Z9;1')
    models.delete_student(sid)
    assert models.get_sammel_texte(k, 'schulweg') == []
