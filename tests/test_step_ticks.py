"""Step ticks live on the server (step_tick), because school PCs wipe
localStorage at logout and every lesson started with all ticks gone."""
import re

import models
from app import topic_slug


def _login_with_topic(client):
    klasse_id = models.create_klasse("6a")
    student_id = models.create_student("Mueller", "Anna", "u1", "pw")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Thema A", "d", "l", "MBI", "6", "pflicht")
    subtask_id = models.create_subtask(task_id, "### A\n\n1. Erster Schritt\n2. Zweiter Schritt", reihenfolge=1)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with client.session_transaction() as sess:
        sess['student_id'] = student_id
    slug = topic_slug(models.get_task(task_id))
    page = client.get(f'/schueler/thema/{slug}').get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    return student_id, subtask_id, slug, token


def _post(client, slug, token, keys):
    return client.post(f'/schueler/thema/{slug}/aufgabe/1/schritte',
                       json={'keys': keys}, headers={'X-CSRFToken': token})


def test_ticks_are_saved_and_come_back_on_the_page(client, db):
    student_id, subtask_id, slug, token = _login_with_topic(client)

    assert _post(client, slug, token, ['abc', 'def', 'abc']).status_code == 200
    assert models.get_step_ticks(student_id, [subtask_id]) == {subtask_id: ['abc', 'def']}

    page = client.get(f'/schueler/thema/{slug}').get_data(as_text=True)
    assert 'new Set(["abc", "def"])' in page


def test_empty_list_removes_the_row(client, db):
    student_id, subtask_id, slug, token = _login_with_topic(client)
    _post(client, slug, token, ['abc'])
    _post(client, slug, token, [])
    assert models.get_step_ticks(student_id, [subtask_id]) == {}


def test_garbage_is_refused(client, db):
    _, _, slug, token = _login_with_topic(client)
    assert _post(client, slug, token, 'abc').status_code == 400
    assert _post(client, slug, token, ['x' * 17]).status_code == 400
    assert client.post(f'/schueler/thema/{slug}/aufgabe/9/schritte',
                       json={'keys': []}, headers={'X-CSRFToken': token}).status_code == 404
