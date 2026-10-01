"""A Seilbahn student at a regular topic is measured like Wanderweg.

Seilbahn is non-cumulative: such a student only does `path: seilbahn` tasks. A topic
without a single one therefore had nothing required for them -- everything showed as
Zusatz and the topic completed at once. That is the mirror of the existing override
for pure Seilbahn topics (models.effective_path_for_topic).

Background: docs/shared/requests/2026-08-31-mbi-akutfall-behoben-systemfrage-offen-kein-datenvertrag.md
"""
import models


def _setup(lernpfad, paths):
    """One student on `lernpfad`, one topic with one Aufgabe per entry in `paths`."""
    student_id = models.create_student("Test", "Kind", "testkind", "pw123", lernpfad=lernpfad)
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "")
    for i, path in enumerate(paths, 1):
        models.create_subtask(task_id, f"Aufgabe {i}", reihenfolge=i, path=path)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)).fetchone()['id']
    return student_id, klasse_id, task_id, student_task_id


def _required(student_id, klasse_id, task_id):
    return [s['required'] for s in
            models.get_visible_subtasks_for_student(student_id, klasse_id, task_id)]


def test_seilbahn_student_at_regular_topic_gets_wanderweg_tasks(db):
    sid, kid, tid, _ = _setup('seilbahn', ['wanderweg', 'bergweg', 'gipfeltour'])
    assert _required(sid, kid, tid) == [True, False, False]


def test_regular_topic_does_not_complete_with_nothing_done(db):
    sid, kid, tid, stid = _setup('seilbahn', ['wanderweg', 'wanderweg', 'bergweg'])
    assert models.check_task_completion(stid) is False

    subtasks = models.get_visible_subtasks_for_student(sid, kid, tid)
    for sub in subtasks[:2]:
        models.toggle_student_subtask(stid, sub['id'], True)
    assert models.check_task_completion(stid) is True


def test_mixed_topic_keeps_the_plain_rule(db):
    """Some Seilbahn tasks in a regular topic: the Seilbahn student does only those."""
    sid, kid, tid, _ = _setup('seilbahn', ['wanderweg', 'seilbahn', 'bergweg'])
    assert _required(sid, kid, tid) == [False, True, False]


def test_pure_seilbahn_topic_unchanged(db):
    sid, kid, tid, _ = _setup('bergweg', ['seilbahn', 'seilbahn'])
    assert _required(sid, kid, tid) == [True, True]


def test_main_path_student_at_regular_topic_unchanged(db):
    sid, kid, tid, _ = _setup('wanderweg', ['wanderweg', 'bergweg'])
    assert _required(sid, kid, tid) == [True, False]


def test_class_page_names_seilbahn_student_at_regular_topic(as_admin):
    sid, kid, _, _ = _setup('seilbahn', ['wanderweg', 'bergweg'])
    roster = models.get_students_in_klasse(kid)
    assert [s['seilbahn_regulaer'] for s in roster] == [1]

    html = as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)
    assert "1 Seilbahn-Schüler an einem regulären Thema" in html
    assert "kein Seilbahn-Thema" in html


def test_class_page_is_quiet_for_the_twin_and_for_main_paths(as_admin):
    sid, kid, _, _ = _setup('seilbahn', ['seilbahn', 'seilbahn'])
    other = models.create_student("Berg", "Kind", "bergkind", "pw123", lernpfad='bergweg')
    models.add_student_to_klasse(other, kid)
    regular = models.create_task("Regulär", "", "", "MBI", "5", "")
    models.create_subtask(regular, "Aufgabe", reihenfolge=1, path='wanderweg')
    models.assign_task_to_student(other, kid, regular)

    assert [s['seilbahn_regulaer'] for s in models.get_students_in_klasse(kid)] == [0, 0]
    html = as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)
    assert "an einem regulären Thema" not in html
    assert "kein Seilbahn-Thema" not in html
