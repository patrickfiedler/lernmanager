"""Bewertungsfenster (Phase 1 of task_plan.md § Notenrechnung): every change logged."""
import pytest

import models


@pytest.fixture
def setup(db):
    klasse_id = models.create_klasse('11z')
    t1 = models.create_task('Modul 1', '', '', 'Chemie', '11', 'pflicht')
    t2 = models.create_task('Modul 2', '', '', 'Chemie', '11', 'pflicht')
    t3 = models.create_task('Modul 3', '', '', 'Chemie', '11', 'pflicht')
    return klasse_id, t1, t2, t3


def _neu(klasse_id, module, stichtag='2099-12-31'):
    return models.create_fenster(klasse_id, 'Fenster II', '2026-11-01', stichtag, module, None)


def test_create_logs_dates_and_modules(setup):
    klasse_id, t1, t2, _ = setup
    f = models.get_fenster(_neu(klasse_id, [t1, t2]))
    assert f['task_ids'] == [t1, t2]
    log = models.get_fenster_log(f['id'])
    assert [e['aktion'] for e in log] == ['angelegt']
    assert 'Modul 1, Modul 2' in log[0]['detail']


def test_every_change_gets_its_own_log_row(setup):
    klasse_id, t1, t2, t3 = setup
    fid = _neu(klasse_id, [t1, t2])
    n = models.update_fenster(fid, 'Fenster II', '2026-11-01', '2099-06-30', [t1, t3], None)
    assert n == 3
    aktionen = sorted((e['aktion'], e['detail']) for e in models.get_fenster_log(fid)
                      if e['aktion'] != 'angelegt')
    assert aktionen == [('daten', 'Stichtag: 2099-12-31 -> 2099-06-30'),
                        ('modul_entfernt', 'Modul 2'), ('modul_hinzu', 'Modul 3')]
    assert models.get_fenster(fid)['task_ids'] == [t1, t3]


def test_saving_unchanged_window_logs_nothing(setup):
    klasse_id, t1, _, _ = setup
    fid = _neu(klasse_id, [t1])
    assert models.update_fenster(fid, 'Fenster II', '2026-11-01', '2099-12-31', [t1], None) == 0
    assert len(models.get_fenster_log(fid)) == 1


@pytest.mark.parametrize('name, start, ende', [
    ('', '2026-11-01', '2027-01-31'),
    ('X', '2026-11-01', ''),
    ('X', '2027-02-01', '2027-01-31'),
])
def test_bad_input_is_refused(setup, name, start, ende):
    klasse_id = setup[0]
    with pytest.raises(ValueError):
        models.create_fenster(klasse_id, name, start, ende, [], None)


def test_admin_page_creates_and_edits(setup, app, as_admin):
    app.config['WTF_CSRF_ENABLED'] = False
    klasse_id, t1, t2, _ = setup
    r = as_admin.post(f'/admin/klasse/{klasse_id}/bewertungsfenster', data={
        'name': 'Fenster II', 'start_datum': '2026-11-01', 'stichtag': '2099-01-31',
        'task_ids': [t1, t2]}, follow_redirects=True)
    assert r.status_code == 200 and 'Änderungsprotokoll' in r.get_data(as_text=True)
    fid = models.list_fenster(klasse_id)[0]['id']
    as_admin.post(f'/admin/bewertungsfenster/{fid}', data={
        'name': 'Fenster II', 'start_datum': '2026-11-01', 'stichtag': '2099-01-31',
        'task_ids': [t1]})
    assert models.get_fenster(fid)['task_ids'] == [t1]
    assert 'Modul entfernt' in as_admin.get(f'/admin/bewertungsfenster/{fid}').get_data(as_text=True)


def test_freezes_the_day_after_the_stichtag(setup):
    f = {'stichtag': '2026-12-18', 'eingefroren_am': None}
    assert not models.fenster_ist_eingefroren(f, heute='2026-12-18')
    assert models.fenster_ist_eingefroren(f, heute='2026-12-19')


def test_frozen_window_refuses_changes_and_delete(setup):
    klasse_id, t1, t2, _ = setup
    fid = models.create_fenster(klasse_id, 'Fenster I', '2020-01-01', '2020-01-31', [t1], None)
    with pytest.raises(ValueError):
        models.update_fenster(fid, 'Fenster I', '2020-01-01', '2020-01-31', [t1, t2], None)
    with pytest.raises(ValueError):
        models.delete_fenster(fid)
    assert models.get_fenster(fid)['task_ids'] == [t1]


def test_manual_freeze_needs_confirmation_and_is_logged(setup, app, as_admin):
    app.config['WTF_CSRF_ENABLED'] = False
    klasse_id, t1, _, _ = setup
    fid = _neu(klasse_id, [t1])
    as_admin.post(f'/admin/bewertungsfenster/{fid}', data={'aktion': 'einfrieren'})
    assert not models.get_fenster(fid)['eingefroren']
    as_admin.post(f'/admin/bewertungsfenster/{fid}', data={'aktion': 'einfrieren', 'bestaetigt': '1'})
    assert models.get_fenster(fid)['eingefroren']
    assert models.get_fenster_log(fid)[0]['aktion'] == 'eingefroren'
    with pytest.raises(ValueError):
        models.update_fenster(fid, 'Neu', '2026-11-01', '2099-12-31', [t1], None)
