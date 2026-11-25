"""Name order per account (migrate_088): "Nachname, Vorname" by default, or
"Vorname Nachname" -- sorting and display follow the same switch."""
import pytest

import models
from import_task import import_task


@pytest.fixture
def klasse(db):
    task_id = import_task({'task': {'name': 'T', 'beschreibung': 'x', 'fach': 'MBI', 'stufe': '5',
                                    'subtasks': [{'beschreibung': '### 1 - A', 'path': 'wanderweg',
                                                  'checkpoint_type': 'abnahme',
                                                  'kern_standard_tag': 'kern'}]}})
    k = models.create_klasse('11z')
    # Nachname order: Adler (Zoe), Bauer (Anna). Vorname order: Anna Bauer, Zoe Adler
    for nach, vor, login in [('Adler', 'Zoe', 'u1'), ('Bauer', 'Anna', 'u2')]:
        models.add_student_to_klasse(models.create_student(nach, vor, login, 'pw'), k)
    return k, models.get_subtasks(task_id)[0]['id']


def page(client, klasse):
    k, sub = klasse
    return client.get(f'/admin/klasse/{k}/checkpoint/{sub}/eintragen').get_data(as_text=True)


def test_default_is_nachname_first(klasse, as_admin):
    html = page(as_admin, klasse)
    assert html.index('Adler, Zoe') < html.index('Bauer, Anna')


def test_switch_changes_sort_and_display(klasse, app, as_admin):
    app.config['WTF_CSRF_ENABLED'] = False
    as_admin.post('/admin/namensreihenfolge', data={'name_order': 'vorname'})
    html = page(as_admin, klasse)
    assert html.index('Anna Bauer') < html.index('Zoe Adler')
    assert 'Adler, Zoe' not in html
    admin_id = models.verify_admin('testadmin', 'testpass')['id']
    assert models.get_admin(admin_id)['name_order'] == 'vorname'


def test_unknown_value_is_ignored(klasse, app, as_admin):
    app.config['WTF_CSRF_ENABLED'] = False
    as_admin.post('/admin/namensreihenfolge', data={'name_order': 'DROP'})
    admin_id = models.verify_admin('testadmin', 'testpass')['id']
    assert models.get_admin(admin_id)['name_order'] == 'nachname'


def test_login_restores_the_choice(db, client):
    models.create_admin('lehrer', 'geheim1')
    admin_id = models.verify_admin('lehrer', 'geheim1')['id']
    models.set_admin_name_order(admin_id, 'vorname')
    client.application.config['WTF_CSRF_ENABLED'] = False
    client.post('/login', data={'username': 'lehrer', 'password': 'geheim1'})
    with client.session_transaction() as sess:
        assert sess['name_order'] == 'vorname'
