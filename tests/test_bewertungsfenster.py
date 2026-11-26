"""Stichtag je Modul (Chemie 2026-11-26: one grade per module). A bewertungsfenster row
is the Stichtag of one module in one class, set on the checkpoint overview, every
change logged. migrate_090 splits the old multi-module windows."""
import importlib
import os
import sqlite3
import sys

import pytest

import config
import models

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrate'))
mig = importlib.import_module('migrate_090_fenster_je_modul')


@pytest.fixture
def setup(db):
    klasse_id = models.create_klasse('11z')
    t1 = models.create_task('Modul 1', '', '', 'Chemie', '11', 'pflicht')
    t3 = models.create_task('Modul 3', '', '', 'Chemie', '11', 'pflicht')
    return klasse_id, t1, t3


def test_no_stichtag_means_none(setup):
    klasse_id, t1, _ = setup
    assert models.get_modul_fenster(klasse_id, t1) is None


def test_set_move_and_log(setup):
    klasse_id, t1, t3 = setup
    assert models.set_modul_stichtag(klasse_id, t1, '2099-01-31', None)
    assert not models.set_modul_stichtag(klasse_id, t1, '2099-01-31', None)   # unchanged
    assert models.set_modul_stichtag(klasse_id, t1, '2099-02-28', None)
    f = models.get_modul_fenster(klasse_id, t1)
    assert (f['name'], f['stichtag'], f['task_ids']) == ('Modul 1', '2099-02-28', [t1])
    assert [e['detail'] for e in models.get_fenster_log(f['id'])] == [
        'Stichtag: 2099-01-31 -> 2099-02-28', 'Stichtag 2099-01-31']
    assert models.get_modul_fenster(klasse_id, t3) is None                    # per module


def test_past_stichtag_is_final_at_once(setup):
    klasse_id, t1, _ = setup
    models.set_modul_stichtag(klasse_id, t1, '2026-11-09', None)   # a module that ended
    assert models.get_modul_fenster(klasse_id, t1)['eingefroren']
    with pytest.raises(ValueError):
        models.set_modul_stichtag(klasse_id, t1, '2026-11-10', None)
    with pytest.raises(ValueError):
        models.remove_modul_stichtag(klasse_id, t1)


def test_remove_before_it_is_past(setup):
    klasse_id, t1, _ = setup
    models.set_modul_stichtag(klasse_id, t1, '2099-01-31', None)
    models.remove_modul_stichtag(klasse_id, t1)
    assert models.get_modul_fenster(klasse_id, t1) is None


@pytest.mark.parametrize('datum', ['', '31.01.2099', None])
def test_bad_date_is_refused(setup, datum):
    klasse_id, t1, _ = setup
    with pytest.raises(ValueError):
        models.set_modul_stichtag(klasse_id, t1, datum, None)


def test_freezes_the_day_after_the_stichtag(setup):
    f = {'stichtag': '2026-12-18', 'eingefroren_am': None}
    assert not models.fenster_ist_eingefroren(f, heute='2026-12-18')
    assert models.fenster_ist_eingefroren(f, heute='2026-12-19')


def test_overview_sets_and_shows_the_stichtag(setup, app, as_admin):
    app.config['WTF_CSRF_ENABLED'] = False
    klasse_id, t1, _ = setup
    as_admin.post('/admin/checkpoint-uebersicht/stichtag',
                  data={'klasse_id': klasse_id, 'task_id': t1, 'stichtag': '2099-01-31'})
    assert models.get_modul_fenster(klasse_id, t1)['stichtag'] == '2099-01-31'
    as_admin.post('/admin/checkpoint-uebersicht/stichtag',
                  data={'klasse_id': klasse_id, 'task_id': t1, 'aktion': 'entfernen'})
    assert models.get_modul_fenster(klasse_id, t1) is None


# ---- migrate_090 ----

def old_window(klasse_id, name, stichtag, task_ids, eingefroren_am=None):
    """A window as the old pages made them: several modules in one row."""
    with models.db_session() as conn:
        fid = conn.execute(
            "INSERT INTO bewertungsfenster (klasse_id, name, start_datum, stichtag, eingefroren_am, "
            "created_at) VALUES (?, ?, '2026-08-01', ?, ?, '2026-11-25 10:00:00')",
            (klasse_id, name, stichtag, eingefroren_am)).lastrowid
        conn.executemany("INSERT INTO bewertungsfenster_modul (fenster_id, task_id) VALUES (?, ?)",
                         [(fid, t) for t in task_ids])
    return fid


def test_migration_splits_a_window_per_module(setup):
    klasse_id, t1, t3 = setup
    fid = old_window(klasse_id, 'Fenster I', '2026-11-09', [t1, t3], '2026-11-25 11:00:00')
    assert mig.run(config.DATABASE)
    m1, m3 = models.get_modul_fenster(klasse_id, t1), models.get_modul_fenster(klasse_id, t3)
    assert m1['id'] == fid and m1['task_ids'] == [t1]
    assert (m3['name'], m3['stichtag'], m3['eingefroren_am'], m3['task_ids']) == (
        'Modul 3', '2026-11-09', '2026-11-25 11:00:00', [t3])
    assert models.get_fenster_log(m3['id'])[0]['aktion'] == 'aufgeteilt'
    assert mig.run(config.DATABASE, probelauf=True)          # nothing left to split


def test_migration_stops_on_a_module_in_two_windows(setup):
    klasse_id, t1, t3 = setup
    old_window(klasse_id, 'Fenster I', '2026-11-09', [t1, t3])
    old_window(klasse_id, 'Modul 3', '2027-01-29', [t3])
    assert not mig.run(config.DATABASE)
    with sqlite3.connect(config.DATABASE) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bewertungsfenster").fetchone()[0] == 2
