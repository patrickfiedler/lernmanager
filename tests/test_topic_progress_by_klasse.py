"""Bearbeitungsstand on admin_thema_detail: how far each class is per Aufgabe,
so an admin sees where a topic can still be changed without moving ticks."""
import models


def _setup(n_subtasks=4):
    task_id = models.create_task('5 - Test', 'x', '', 'MBI', '5', 'pflicht')
    subs = [models.create_subtask(task_id, f'### Aufgabe {i + 1}', reihenfolge=i) for i in range(n_subtasks)]
    klasse_id = models.create_klasse('5a')
    return task_id, subs, klasse_id


def _student(klasse_id, task_id, name, ticked):
    sid = models.create_student(name, 'X', name.lower(), 'pw')
    models.add_student_to_klasse(sid, klasse_id)
    models.assign_task_to_student(sid, klasse_id, task_id)
    st_id = models.get_student_task(sid, klasse_id)['id']
    for sub_id in ticked:
        models.toggle_student_subtask(st_id, sub_id, True)
    return st_id


def test_done_passed_and_frei_ab(db):
    task_id, subs, klasse_id = _setup()
    _student(klasse_id, task_id, 'Anna', [subs[0], subs[1]])
    _student(klasse_id, task_id, 'Ben', [subs[0], subs[2]])   # skipped Aufgabe 2
    _student(klasse_id, task_id, 'Cem', [])

    progress = models.get_topic_progress_by_klasse(task_id)
    [k] = progress['klassen']
    assert k['aktiv'] == 3
    cells = [k['cells'][s] for s in subs]
    assert [c['done'] for c in cells] == [2, 1, 1, 0]
    assert [c['passed'] for c in cells] == [2, 2, 1, 0]
    assert progress['frei_ab'] == 4


def test_frei_ab_none_when_last_ticked(db):
    task_id, subs, klasse_id = _setup(2)
    _student(klasse_id, task_id, 'Anna', [subs[1]])
    assert models.get_topic_progress_by_klasse(task_id)['frei_ab'] is None


def test_finished_students_not_counted_as_open(db):
    task_id, subs, klasse_id = _setup(2)
    st_id = _student(klasse_id, task_id, 'Anna', subs)
    with models.db_session() as conn:
        conn.execute("UPDATE student_task SET abgeschlossen = 1 WHERE id = ?", (st_id,))
    other = _student(klasse_id, task_id, 'Ben', [])
    [k] = models.get_topic_progress_by_klasse(task_id)['klassen']
    assert (k['aktiv'], k['fertig']) == (1, 1)
    assert models.get_topic_progress_by_klasse(task_id)['frei_ab'] == 1
    with models.db_session() as conn:
        conn.execute("UPDATE student_task SET abgeschlossen = 1 WHERE id = ?", (other,))
    assert models.get_topic_progress_by_klasse(task_id)['klassen'] == []


def test_tick_before_content_change_is_stale(db):
    task_id, subs, klasse_id = _setup(2)
    st_id = _student(klasse_id, task_id, 'Anna', [subs[0]])
    with models.db_session() as conn:
        conn.execute("UPDATE student_subtask SET completed_at = '2026-11-01' WHERE student_task_id = ?", (st_id,))
    models.update_subtasks(task_id, ['### Neu an Stelle 1', '### Aufgabe 2'])
    [k] = models.get_topic_progress_by_klasse(task_id)['klassen']
    assert k['cells'][subs[0]]['stale'] == 1
    assert k['cells'][subs[1]]['stale'] == 0


def test_page_shows_table(as_admin):
    task_id, subs, klasse_id = _setup(2)
    _student(klasse_id, task_id, 'Anna', [subs[0]])
    html = as_admin.get(f'/admin/thema/{task_id}').get_data(as_text=True)
    assert '📊 Bearbeitungsstand' in html
    assert 'Ab Aufgabe 2 hat noch niemand' in html
    assert '1 erledigt · 1 weiter' in html


def test_page_without_students_has_no_table(as_admin):
    task_id, _, _ = _setup(2)
    html = as_admin.get(f'/admin/thema/{task_id}').get_data(as_text=True)
    assert '📊 Bearbeitungsstand' not in html
