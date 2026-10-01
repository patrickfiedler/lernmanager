"""Assignment follows the link between a regular topic and its Seilbahn twin.

Decided by Patrick 2026-10-01 (MBI request 2026-08-31, layer 3):
  1. assigning a regular topic gives a Seilbahn student its twin -- class-wide and single
  2. the queue's "Nächstes Thema" starts the twin, and the twin counts as that entry
  3. students already at the regular topic can be moved from the class page
"""
import models


def _pair(name="2 - Alltag", slug="kl6_alltag"):
    regular = models.create_task(name, "", "", "MBI", "6", "", unit_slug=slug)
    models.create_subtask(regular, "Aufgabe", reihenfolge=1, path='wanderweg')
    twin = models.create_task(name, "", "", "MBI", "6", "", unit_slug=f"seilbahn_{slug}")
    models.create_subtask(twin, "Aufgabe", reihenfolge=1, path='seilbahn')
    models.set_task_seilbahn_of(twin, slug)
    return regular, twin


def _class():
    kid = models.create_klasse("Testklasse")
    seil = models.create_student("Seil", "Bahn", "seilbahn", "pw123", lernpfad='seilbahn')
    berg = models.create_student("Berg", "Weg", "bergweg", "pw123", lernpfad='bergweg')
    for sid in (seil, berg):
        models.add_student_to_klasse(sid, kid)
    return kid, seil, berg


def _topics(student_id, klasse_id, active_only=False):
    return [t['task_id'] for t in models.get_all_student_tasks(student_id, klasse_id)
            if not (active_only and t['abgeschlossen'])]


def test_class_assignment_gives_seilbahn_student_the_twin(db):
    kid, seil, berg = _class()
    regular, twin = _pair()
    counts = models.assign_task_to_klasse(kid, regular)

    assert _topics(seil, kid) == [twin]
    assert _topics(berg, kid) == [regular]
    assert counts['created'] == 2 and counts['zwilling'] == 1


def test_single_assignment_gives_seilbahn_student_the_twin(db):
    kid, seil, _ = _class()
    regular, twin = _pair()
    assert models.assign_task_to_student(seil, kid, regular, on_existing='reopen') == 'created'
    assert _topics(seil, kid) == [twin]


def test_topic_without_twin_is_assigned_as_it_is(db):
    kid, seil, _ = _class()
    regular = models.create_task("Ohne Zwilling", "", "", "MBI", "6", "", unit_slug='kl6_ohne')
    models.assign_task_to_klasse(kid, regular)
    assert _topics(seil, kid) == [regular]


def test_class_assignment_leaves_a_student_at_the_regular_topic(db):
    """Assigned before the pair was linked: a class-wide assignment must not move them."""
    kid, seil, _ = _class()
    regular = models.create_task("2 - Alltag", "", "", "MBI", "6", "", unit_slug='kl6_alltag')
    models.assign_task_to_klasse(kid, regular)
    twin = models.create_task("2 - Alltag", "", "", "MBI", "6", "", unit_slug='seilbahn_kl6_alltag')
    models.create_subtask(twin, "Aufgabe", reihenfolge=1, path='seilbahn')
    models.set_task_seilbahn_of(twin, 'kl6_alltag')

    counts = models.assign_task_to_klasse(kid, regular)
    assert _topics(seil, kid) == [regular]
    assert counts['skipped'] == 2


def test_move_closes_the_regular_topic_and_starts_the_twin(db):
    kid, seil, berg = _class()
    regular = models.create_task("2 - Alltag", "", "", "MBI", "6", "", unit_slug='kl6_alltag')
    models.create_subtask(regular, "Aufgabe", reihenfolge=1, path='wanderweg')
    models.assign_task_to_klasse(kid, regular)
    twin = models.create_task("2 - Alltag", "", "", "MBI", "6", "", unit_slug='seilbahn_kl6_alltag')
    models.create_subtask(twin, "Aufgabe", reihenfolge=1, path='seilbahn')
    models.set_task_seilbahn_of(twin, 'kl6_alltag')

    flags = {s['id']: (s['seilbahn_regulaer'], s['zwilling_id']) for s in models.get_students_in_klasse(kid)}
    assert flags[seil] == (1, twin)

    assert models.move_seilbahn_students_to_twin(kid) == 1
    assert _topics(seil, kid, active_only=True) == [twin]
    assert sorted(_topics(seil, kid)) == sorted([regular, twin])   # regular stays in the history
    assert _topics(berg, kid, active_only=True) == [regular]
    assert models.move_seilbahn_students_to_twin(kid) == 0


def test_class_page_offers_the_move_only_with_a_twin(as_admin, app):
    app.config["WTF_CSRF_ENABLED"] = False
    kid, seil, _ = _class()
    regular = models.create_task("2 - Alltag", "", "", "MBI", "6", "", unit_slug='kl6_alltag')
    models.create_subtask(regular, "Aufgabe", reihenfolge=1, path='wanderweg')
    models.assign_task_to_klasse(kid, regular)

    html = as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)
    assert "kein Zwilling" in html and "umhängen" not in html

    twin = models.create_task("2 - Alltag", "", "", "MBI", "6", "", unit_slug='seilbahn_kl6_alltag')
    models.create_subtask(twin, "Aufgabe", reihenfolge=1, path='seilbahn')
    models.set_task_seilbahn_of(twin, 'kl6_alltag')
    html = as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)
    assert "1 auf den Seilbahn-Zwilling umhängen" in html

    as_admin.post(f"/admin/klasse/{kid}/seilbahn-umhaengen")
    assert _topics(seil, kid, active_only=True) == [twin]
    assert "an einem regulären Thema" not in as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)


def test_queue_starts_the_twin_and_then_moves_on(client, app):
    app.config["WTF_CSRF_ENABLED"] = False
    kid, seil, _ = _class()
    regular, twin = _pair()
    third = models.create_task("3 - Danach", "", "", "MBI", "6", "", unit_slug='kl6_danach')
    models.set_topic_queue(kid, [regular, third])

    assert models.get_next_open_queued_topic(seil, kid)['task_id'] == regular
    with client.session_transaction() as sess:
        sess["student_id"] = seil
    resp = client.post("/schueler/naechstes-thema", data={'task_id': regular, 'klasse_id': kid})
    assert _topics(seil, kid) == [twin]
    assert client.get(resp.headers['Location']).status_code == 200   # the link lands on the twin

    # The twin stands for the regular topic's queue entry: next is the third topic,
    # not the regular one again.
    assert models.get_next_open_queued_topic(seil, kid, twin)['task_id'] == third
    assert regular in models.get_assigned_task_ids_by_student(kid)[seil]

    html_admin_lookup = {s['id']: s for s in models.get_students_in_klasse(kid)}
    assert html_admin_lookup[seil]['task_id'] == twin


def test_class_page_shows_queue_position_for_the_twin(as_admin):
    kid, seil, _ = _class()
    regular, twin = _pair()
    third = models.create_task("3 - Danach", "", "", "MBI", "6", "", unit_slug='kl6_danach')
    models.set_topic_queue(kid, [regular, third])
    models.assign_task_to_klasse(kid, regular)
    html = as_admin.get(f"/admin/klasse/{kid}").get_data(as_text=True)
    assert html.count("(1/2)") == 2
