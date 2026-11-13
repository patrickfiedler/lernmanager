"""Zeilen sammeln (MBI request 2026-11-11, Kl.7 Unit 3 Schulweg-Daten).

Aufgabe 1 collects one line per student, Aufgabe 2 lets the class download all
lines of its own class as .txt, without names, sorted, exactly as typed.
"""
import pytest

import import_task
import models

KOPF = 'Code;Minuten;km;Verkehrsmittel'
T = 'kl7_tabellen'   # the Thema key (models.sammel_thema) of _data()


def _data():
    return {'task': {
        'name': 'Tabellen', 'beschreibung': 'Schulweg', 'lernziel': '', 'fach': 'MBI',
        'unit_slug': T,
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
    models.approve_sammel_zeilen(k7a, T, 'schulweg')
    models.approve_sammel_zeilen(k7b, T, 'schulweg')

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


def test_text_box_shows_same_lines_as_file(app, client):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    models.set_sammel_zeile(k, T, 'schulweg', sid, 'A1;<b>5</b>')
    models.approve_sammel_zeilen(k, T, 'schulweg')
    _login(client, sid)
    html = client.get('/schueler/thema/tabellen?aufgabe=2').get_data(as_text=True)
    assert f'{KOPF}\nA1;&lt;b&gt;5&lt;/b&gt;</textarea>' in html  # escaped, header first
    assert 'herunterladen' in html


def test_anzeige_switch(app, client):
    data = _data()
    data['task']['subtasks'][1]['sammeln_download']['anzeige'] = 'textfeld'
    k = models.create_klasse('7a')
    task_id = import_task.import_task(data)
    anna = _student('anna', k, task_id)
    models.set_sammel_zeile(k, T, 'schulweg', anna, 'Z9;1')
    models.approve_sammel_zeilen(k, T, 'schulweg')
    _login(client, anna)
    html = client.get('/schueler/thema/tabellen?aufgabe=2').get_data(as_text=True)
    assert 'sammel-daten' in html and 'sammlung.txt' not in html
    assert client.get('/schueler/thema/tabellen/aufgabe/2/sammlung.txt').status_code == 404

    data['task']['subtasks'][1]['sammeln_download']['anzeige'] = 'kopieren'
    assert 'anzeige muss eins von' in _errors(data)


def test_empty_line_deletes_own_entry(app, client):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    _login(client, sid)
    client.post('/schueler/thema/tabellen/aufgabe/1/zeile', data={'zeile': 'Z9;1'})
    client.post('/schueler/thema/tabellen/aufgabe/1/zeile', data={'zeile': ''})
    assert models.get_sammel_texte(k, T, 'schulweg') == []


def test_shuffle_differs_between_students_and_keeps_all_lines(db):
    k = models.create_klasse('7a')
    for i in range(20):
        sid = models.create_student('N', f's{i}', f's{i}', 'pw')
        models.set_sammel_zeile(k, T, 'schulweg', sid, f'Zeile {i:02d}')
    models.approve_sammel_zeilen(k, T, 'schulweg')
    plain = models.get_sammel_texte(k, T, 'schulweg')
    a = models.get_sammel_texte(k, T, 'schulweg', shuffle_for=1)
    b = models.get_sammel_texte(k, T, 'schulweg', shuffle_for=2)
    assert sorted(a) == sorted(b) == plain
    assert a != b and a != plain


def test_rows_survive_reimport(db):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    models.set_sammel_zeile(k, T, 'schulweg', sid, 'Z9;1')
    models.approve_sammel_zeilen(k, T, 'schulweg')
    import_task.import_task(_data())
    assert models.get_sammel_texte(k, T, 'schulweg') == ['Z9;1']


def test_teacher_rejects_nonsense_kept_for_audit_hidden_from_class(app, client, as_admin):
    k7a, k7b = models.create_klasse('7a'), models.create_klasse('7b')
    task_id = import_task.import_task(_data())
    anna = _student('anna', k7a, task_id)
    ben = _student('ben', k7a, task_id)
    models.set_sammel_zeile(k7a, T, 'schulweg', anna, 'Z9;10')
    models.set_sammel_zeile(k7a, T, 'schulweg', ben, 'Unsinn')
    models.approve_sammel_zeilen(k7a, T, 'schulweg')            # waved through by mistake
    zeilen = {z['text']: z for z in models.get_sammel_zeilen_for_klasse(k7a)[0]['zeilen']}
    unsinn_id, anna_id = zeilen['Unsinn']['id'], zeilen['Z9;10']['id']

    as_admin.post(f'/admin/klasse/{k7b}/sammel-zeile/{unsinn_id}/ablehnen')  # wrong class: nothing
    assert 'Unsinn' in models.get_sammel_texte(k7a, T, 'schulweg')
    as_admin.post(f'/admin/klasse/{k7a}/sammel-zeile/{unsinn_id}/ablehnen')
    assert models.get_sammel_texte(k7a, T, 'schulweg') == ['Z9;10']

    # Kept for audit, and a later edit does not erase it
    models.set_sammel_zeile(k7a, T, 'schulweg', ben, 'B2;5')
    html = as_admin.get(f'/admin/klasse/{k7a}').get_data(as_text=True)
    assert 'abgelehnt: <code>Unsinn</code>' in html and 'sammel-zeile/' + str(unsinn_id) + '/loeschen' not in html

    # Changed approved line rejected: the approved version stays in the data
    models.set_sammel_zeile(k7a, T, 'schulweg', anna, 'Quatsch')
    models.set_sammel_zeile_abgelehnt(anna_id, k7a, True)
    models.approve_sammel_zeilen(k7a, T, 'schulweg')              # skips rejected, takes ben's B2;5
    assert sorted(models.get_sammel_texte(k7a, T, 'schulweg')) == ['B2;5', 'Z9;10']

    _login(client, anna)
    html = client.get('/schueler/thema/tabellen?aufgabe=1').get_data(as_text=True)
    assert 'nicht freigegeben' in html

    models.set_sammel_zeile_abgelehnt(anna_id, k7a, False)    # take back: waits again
    assert models.get_sammel_zeilen_for_klasse(k7a)[0]['wartend'] == 1


def test_deleting_student_deletes_their_line(db):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    models.set_sammel_zeile(k, T, 'schulweg', sid, 'Z9;1')
    models.delete_student(sid)
    assert models.get_sammel_texte(k, T, 'schulweg') == []


def test_lines_wait_for_approval_late_entry_and_change(app, client, as_admin):
    """Nothing reaches the class before the teacher approves; a late entry or a
    change waits too, and until then the class keeps the approved version."""
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    anna, ben, carl = (_student(n, k, task_id) for n in ('anna', 'ben', 'carl'))
    models.set_sammel_zeile(k, T, 'schulweg', anna, 'Z9;10')
    models.set_sammel_zeile(k, T, 'schulweg', ben, 'A1;5')

    _login(client, anna)
    html = client.get('/schueler/thema/tabellen?aufgabe=2').get_data(as_text=True)
    assert 'gibt die Daten deiner Klasse bald frei' in html and 'sammel-daten' not in html
    html = client.get('/schueler/thema/tabellen?aufgabe=1').get_data(as_text=True)
    assert 'gibt deine Zeile bald frei' in html

    info = models.get_sammel_zeilen_for_klasse(k)[0]
    assert info['wartend'] == 2 and info['fehlen'] == ['carl N']
    admin_id = models.verify_admin('testadmin', 'testpass')['id']
    with client.session_transaction() as sess:  # client and as_admin are one client
        sess.clear()
        sess['admin_id'] = admin_id
    as_admin.post(f'/admin/klasse/{k}/sammlung/freigeben', data={'thema': T, 'sammel_id': 'schulweg'})
    assert sorted(models.get_sammel_texte(k, T, 'schulweg')) == ['A1;5', 'Z9;10']

    models.set_sammel_zeile(k, T, 'schulweg', anna, 'Z9;12')   # change
    models.set_sammel_zeile(k, T, 'schulweg', carl, 'B7;20')   # absent last lesson
    assert sorted(models.get_sammel_texte(k, T, 'schulweg')) == ['A1;5', 'Z9;10']
    html = as_admin.get(f'/admin/klasse/{k}').get_data(as_text=True)
    assert '2 warten auf Freigabe' in html and 'in den Daten: <code>Z9;10</code>' in html

    assert models.approve_sammel_zeilen(k, T, 'schulweg') == 2
    assert sorted(models.get_sammel_texte(k, T, 'schulweg')) == ['A1;5', 'B7;20', 'Z9;12']
    assert models.get_sammel_zeilen_for_klasse(k)[0]['fehlen'] == []


def test_approval_is_scoped_to_the_class(db):
    k7a, k7b = models.create_klasse('7a'), models.create_klasse('7b')
    task_id = import_task.import_task(_data())
    models.set_sammel_zeile(k7a, T, 'schulweg', _student('anna', k7a, task_id), 'x')
    models.set_sammel_zeile(k7b, T, 'schulweg', _student('ben', k7b, task_id), 'y')
    models.approve_sammel_zeilen(k7a, T, 'schulweg')
    assert models.get_sammel_texte(k7b, T, 'schulweg') == []


@pytest.mark.parametrize('text,verdacht', [
    ('=1+1', True), ('A1;=HYPERLINK("x";"y")', True), ('12; @SUM(1;1)', True),
    ('5;+cmd', True), ("=cmd|' /C calc'!A0", True),
    ('-5;3,5;Bus', False), ('+5', False), ('A1;12;1 km;Fuß', False), ('', False),
])
def test_formula_hint(text, verdacht):
    assert models.sammel_formel_verdacht(text) is verdacht


def test_formula_hint_shown_on_class_page(app, as_admin):
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    models.set_sammel_zeile(k, T, 'schulweg', _student('anna', k, task_id), 'A1;=1+1')
    assert '⚠️ Formel?' in as_admin.get(f'/admin/klasse/{k}').get_data(as_text=True)


def _zweites_thema(name, slug):
    data = _data()
    data['task'].update(name=name, unit_slug=slug)
    return import_task.import_task(data)


def test_same_id_in_two_themen_stays_apart(app, as_admin):
    """Collections belong to their Thema (migrate_080): a generic id in two
    Themen of one class must not merge their lines."""
    k = models.create_klasse('7a')
    t1 = import_task.import_task(_data())
    t2 = _zweites_thema('Diagramme', 'kl7_diagramme')
    anna = _student('anna', k, t1)
    models.assign_task_to_student(anna, k, t2)
    assert models.sammel_thema(t1) == T and models.sammel_thema(t2) == 'kl7_diagramme'
    models.set_sammel_zeile(k, T, 'schulweg', anna, 'aus Tabellen')
    models.set_sammel_zeile(k, 'kl7_diagramme', 'schulweg', anna, 'aus Diagramme')
    models.approve_sammel_zeilen(k, T, 'schulweg')
    assert models.get_sammel_texte(k, T, 'schulweg') == ['aus Tabellen']
    assert models.get_sammel_texte(k, 'kl7_diagramme', 'schulweg') == []

    html = as_admin.get(f'/admin/klasse/{k}').get_data(as_text=True)
    assert 'Tabellen' in html and 'Diagramme' in html


def test_seilbahn_twin_fills_the_same_collection(db):
    k = models.create_klasse('7a')
    regular = import_task.import_task(_data())
    twin = _zweites_thema('Tabellen (Seilbahn)', 'seilbahn_kl7_tabellen')
    models.set_task_seilbahn_of(twin, T)
    assert models.sammel_thema(twin) == models.sammel_thema(regular) == T


def test_migration_080_backfills_the_thema(db):
    import importlib, os, sys, sqlite3, config
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrate'))
    k = models.create_klasse('7a')
    task_id = import_task.import_task(_data())
    sid = _student('anna', k, task_id)
    conn = sqlite3.connect(config.DATABASE)   # back to the migrate_079 schema
    conn.executescript("""
        DROP TABLE sammel_zeile; DROP TABLE sammel_zeile_log;
        CREATE TABLE sammel_zeile (id INTEGER PRIMARY KEY AUTOINCREMENT, klasse_id INTEGER NOT NULL,
            sammel_id TEXT NOT NULL, student_id INTEGER NOT NULL, text TEXT NOT NULL,
            geaendert TEXT NOT NULL DEFAULT (datetime('now','localtime')), text_frei TEXT,
            abgelehnt INTEGER NOT NULL DEFAULT 0, UNIQUE (klasse_id, sammel_id, student_id));
        CREATE TABLE sammel_zeile_log (id INTEGER PRIMARY KEY AUTOINCREMENT, klasse_id INTEGER NOT NULL,
            sammel_id TEXT NOT NULL, student_id INTEGER NOT NULL, aktion TEXT NOT NULL, text TEXT,
            admin_id INTEGER, zeit TEXT NOT NULL DEFAULT (datetime('now','localtime')));
    """)
    conn.execute("INSERT INTO sammel_zeile (klasse_id, sammel_id, student_id, text, text_frei) "
                 "VALUES (?, 'schulweg', ?, 'Z9;1', 'Z9;1')", (k, sid))
    conn.execute("INSERT INTO sammel_zeile_log (klasse_id, sammel_id, student_id, aktion) "
                 "VALUES (?, 'schulweg', ?, 'gespeichert')", (k, sid))
    conn.commit()
    conn.close()

    mod = importlib.import_module('migrate_080_sammel_thema')
    mod.DATABASE = config.DATABASE  # captured at import time
    mod.run()
    mod.run()  # idempotent

    assert models.get_sammel_texte(k, T, 'schulweg') == ['Z9;1']
    assert models.get_sammel_zeilen_for_klasse(k)[0]['zeilen'][0]['verlauf'][0]['aktion'] == 'gespeichert'
