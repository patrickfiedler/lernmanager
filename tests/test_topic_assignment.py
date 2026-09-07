"""Reassignment must never cost a student their progress.

student_subtask hangs off student_task.id, not off (student_id, subtask_id), so
a second student_task row for a topic the student already did is an empty one:
every checkmark stays on the old row and the topic reappears at 0 %. The guard
in assign_task_to_student is what stops that, and it used to be dead code -- it
looked for an active row *after* completing every active row, so it always
counted zero and always inserted.
"""
import re

import models


def _setup(db_unused=None):
    klasse_id = models.create_klasse("6a")
    student_id = models.create_student("Mueller", "Anna", "u1", "pw")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Thema A", "d", "l", "MBI", "6", "pflicht")
    subtask_id = models.create_subtask(task_id, "Aufgabe 1", reihenfolge=1)
    return klasse_id, student_id, task_id, subtask_id


def _rows(student_id, klasse_id, task_id):
    with models.db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, abgeschlossen FROM student_task WHERE student_id = ? "
            "AND klasse_id = ? AND task_id = ? ORDER BY id",
            (student_id, klasse_id, task_id)).fetchall()]


def test_reassigning_a_finished_topic_does_not_duplicate_it(db):
    klasse_id, student_id, task_id, subtask_id = _setup()
    models.assign_task_to_student(student_id, klasse_id, task_id)
    st = models.get_student_task(student_id, klasse_id)
    models.toggle_student_subtask(st['id'], subtask_id, True)
    models.mark_task_complete(st['id'], manual=True)

    assert models.assign_task_to_student(student_id, klasse_id, task_id) == 'skipped'

    rows = _rows(student_id, klasse_id, task_id)
    assert len(rows) == 1, "a second, empty row would show the topic at 0 %"
    assert rows[0]['abgeschlossen'] == 1


def test_skip_leaves_a_different_active_topic_alone(db):
    """Assigning a finished topic must not close whatever the student moved on
    to -- 'skip' means do nothing, not 'do nothing except step 1'."""
    klasse_id, student_id, task_a, _ = _setup()
    task_b = models.create_task("Thema B", "d", "l", "MBI", "6", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, task_a)
    models.mark_task_complete(models.get_student_task(student_id, klasse_id)['id'])
    models.assign_task_to_student(student_id, klasse_id, task_b)

    models.assign_task_to_student(student_id, klasse_id, task_a)

    active = models.get_student_task(student_id, klasse_id)
    assert active['task_id'] == task_b


def test_reopen_revives_the_existing_row_with_its_progress(db):
    klasse_id, student_id, task_id, subtask_id = _setup()
    models.assign_task_to_student(student_id, klasse_id, task_id)
    original = models.get_student_task(student_id, klasse_id)
    models.toggle_student_subtask(original['id'], subtask_id, True)
    models.mark_task_complete(original['id'], manual=True)

    assert models.assign_task_to_student(
        student_id, klasse_id, task_id, on_existing='reopen') == 'reopened'

    active = models.get_student_task(student_id, klasse_id)
    assert active['id'] == original['id'], "a new row would be an empty one"
    assert active['manuell_abgeschlossen'] == 0
    progress = models.get_student_subtask_progress(active['id'])
    assert [p['erledigt'] for p in progress] == [1]
    assert len(_rows(student_id, klasse_id, task_id)) == 1


def test_reopen_closes_the_topic_it_replaces(db):
    klasse_id, student_id, task_a, _ = _setup()
    task_b = models.create_task("Thema B", "d", "l", "MBI", "6", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, task_a)
    models.mark_task_complete(models.get_student_task(student_id, klasse_id)['id'])
    models.assign_task_to_student(student_id, klasse_id, task_b)

    models.assign_task_to_student(student_id, klasse_id, task_a, on_existing='reopen')

    assert models.get_student_task(student_id, klasse_id)['task_id'] == task_a
    all_rows = models.get_all_student_tasks(student_id, klasse_id)
    assert [r['abgeschlossen'] for r in all_rows if r['task_id'] == task_b] == [1]


def test_assigning_to_a_class_picks_up_stragglers_without_resetting_the_rest(db):
    """The move that triggered the bug in production: set a queue, then assign
    the topic to the whole class to catch whoever had not started it."""
    klasse_id, done_student, task_id, subtask_id = _setup()
    fresh_student = models.create_student("Schmidt", "Ben", "u2", "pw")
    models.add_student_to_klasse(fresh_student, klasse_id)

    st = models.get_student_task(done_student, klasse_id)
    models.assign_task_to_student(done_student, klasse_id, task_id)
    st = models.get_student_task(done_student, klasse_id)
    models.toggle_student_subtask(st['id'], subtask_id, True)
    models.mark_task_complete(st['id'], manual=True)

    counts = models.assign_task_to_klasse(klasse_id, task_id)

    assert counts == {'created': 1, 'reopened': 0, 'skipped': 1}
    assert len(_rows(done_student, klasse_id, task_id)) == 1
    assert models.get_student_task(fresh_student, klasse_id)['task_id'] == task_id


def test_starting_the_next_topic_twice_is_harmless(client, db):
    """A stale page or a double click posts the same topic twice. The second
    post must not create an empty duplicate row."""
    klasse_id, student_id, task_a, _ = _setup()
    task_b = models.create_task("Thema B", "d", "l", "MBI", "6", "pflicht")
    models.set_topic_queue(klasse_id, [task_a, task_b])
    models.assign_task_to_student(student_id, klasse_id, task_a)
    models.mark_task_complete(models.get_student_task(student_id, klasse_id)['id'])

    with client.session_transaction() as sess:
        sess['student_id'] = student_id
    page = client.get('/schueler').get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    form = {'task_id': task_b, 'klasse_id': klasse_id, 'csrf_token': token}
    client.post('/schueler/naechstes-thema', data=form)
    client.post('/schueler/naechstes-thema', data=form)

    assert len(_rows(student_id, klasse_id, task_b)) == 1


def test_dashboard_names_the_end_of_the_queue(client, db):
    """Queue worked through and nothing active: the page used to end on a blank
    space, which is what 'kein Knopf erschien' looked like from the student's
    side."""
    klasse_id, student_id, task_a, _ = _setup()
    models.set_topic_queue(klasse_id, [task_a])
    models.assign_task_to_student(student_id, klasse_id, task_a)
    models.mark_task_complete(models.get_student_task(student_id, klasse_id)['id'])

    with client.session_transaction() as sess:
        sess['student_id'] = student_id
    html = client.get('/schueler').get_data(as_text=True)

    assert 'Du hast alles geschafft' in html


def test_admin_can_still_reach_a_student_without_an_active_topic(as_admin, db):
    """The completion button hung off get_student_task(), which returns nothing
    once the topic is done -- so the class row lost its only handle."""
    klasse_id, student_id, task_a, _ = _setup()
    models.set_topic_queue(klasse_id, [task_a])
    models.assign_task_to_student(student_id, klasse_id, task_a)
    models.mark_task_complete(models.get_student_task(student_id, klasse_id)['id'])

    html = as_admin.get(f'/admin/schueler/{student_id}').get_data(as_text=True)

    assert 'Themen-Reihenfolge abgearbeitet' in html
