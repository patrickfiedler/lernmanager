"""A student who has finished a unit always gets a link to the next topic.

Three ways the old code stranded them, all seen in production:

1. `abgeschlossen` is written as a side effect of the action that finishes the last
   requirement. When the finish line moves afterwards instead -- a teacher hides an
   Aufgabe, changes the lernpfad, turns subtask_quiz_required off -- no student action
   follows and the flag stays 0. Done and stuck at the same time.
2. The topic page hid the topic quiz AND the next-topic card behind
   `capstone_gate_passed`, although check_task_completion stopped treating a gate as
   blocking on 2026-09-03. A failing upload meant no quiz -> never abgeschlossen ->
   no way out.
3. get_next_queued_topic() read position+1 and nothing else: a topic assigned outside
   the queue has no position (-> None), and position+1 may be one the student already
   finished.
"""
import io
import json
import config
import models

from tests.test_artifact_extraction import make_docx

GATE_CONFIG = {"format": [".docx"], "required_text": ["Fachraumregeln"]}
FAIL_BODY = '<w:p><w:r><w:t>Nichts davon steht hier.</w:t></w:r></w:p>'


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


# --- 3. the queue lookup finds what is open, not what sits at position+1 ---

def test_queue_lookup_skips_topics_the_student_already_did(db):
    student_id = models.create_student("Alex", "Schueler", "queue1", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    a = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    b = models.create_task("Thema B", "", "", "MBI", "5", "pflicht")
    c = models.create_task("Thema C", "", "", "MBI", "5", "pflicht")
    models.set_topic_queue(klasse_id, [a, b, c])

    # B was already done out of order; finishing A must point past it, not back into it.
    models.assign_task_to_student(student_id, klasse_id, b)
    models.assign_task_to_student(student_id, klasse_id, a)

    nxt = models.get_next_open_queued_topic(student_id, klasse_id, a)
    assert nxt["task_id"] == c


def test_queue_lookup_works_for_a_topic_that_is_not_in_the_queue(db):
    """Manual assignment is the documented exception to the queue -- it must not
    cost the student every later link."""
    student_id = models.create_student("Alex", "Schueler", "queue2", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    extra = models.create_task("Extra-Thema", "", "", "MBI", "5", "pflicht")
    a = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    models.set_topic_queue(klasse_id, [a])
    models.assign_task_to_student(student_id, klasse_id, extra)

    nxt = models.get_next_open_queued_topic(student_id, klasse_id, extra)
    assert nxt["task_id"] == a


def test_queue_lookup_returns_none_when_nothing_is_left(db):
    student_id = models.create_student("Alex", "Schueler", "queue3", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    a = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    models.set_topic_queue(klasse_id, [a])
    models.assign_task_to_student(student_id, klasse_id, a)

    assert models.get_next_open_queued_topic(student_id, klasse_id, a) is None


# --- 1. a stale abgeschlossen flag heals on the next page view ---

def test_hiding_the_last_open_aufgabe_releases_the_next_topic_link(app, client):
    """The teacher moves the finish line; the student never clicks again. Before the
    read-path refresh this student stayed on a finished topic forever."""
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Alex", "Schueler", "stale1", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    a = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    b = models.create_task("Thema B", "", "", "MBI", "5", "pflicht")
    done = models.create_subtask(a, "Erledigt", reihenfolge=1)
    leftover = models.create_subtask(a, "Bleibt liegen", reihenfolge=2)
    models.set_topic_queue(klasse_id, [a, b])
    models.assign_task_to_student(student_id, klasse_id, a)
    student_task = models.get_student_task(student_id, klasse_id)
    models.toggle_student_subtask(student_task["id"], done, True)
    assert not models.get_student_task(student_id, klasse_id)["abgeschlossen"]

    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET hidden = 1 WHERE id = ?", (leftover,))

    _login(client, student_id)
    page = client.get("/schueler/thema/thema-a").get_data(as_text=True)
    assert "Nächstes Thema starten" in page
    # get_student_task() only ever returns the ACTIVE topic, so the flag having flipped
    # is exactly why it is None here now.
    assert models.get_student_task(student_id, klasse_id) is None
    rows = models.get_all_student_tasks(student_id, klasse_id)
    assert next(r["abgeschlossen"] for r in rows if r["task_id"] == a)


def test_dashboard_heals_the_same_stale_flag(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Alex", "Schueler", "stale2", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    a = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    b = models.create_task("Thema B", "", "", "MBI", "5", "pflicht")
    done = models.create_subtask(a, "Erledigt", reihenfolge=1)
    leftover = models.create_subtask(a, "Bleibt liegen", reihenfolge=2)
    models.set_topic_queue(klasse_id, [a, b])
    models.assign_task_to_student(student_id, klasse_id, a)
    student_task = models.get_student_task(student_id, klasse_id)
    models.toggle_student_subtask(student_task["id"], done, True)
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET hidden = 1 WHERE id = ?", (leftover,))

    _login(client, student_id)
    page = client.get("/schueler").get_data(as_text=True)
    assert "Nächstes Thema starten" in page


# --- 2. a failing artifact gate advises, it does not lock the exit ---

def test_failing_capstone_gate_still_shows_the_next_topic(app, client, tmp_path):
    """Gates were made advisory on 2026-09-03 in check_task_completion, but the
    template kept enforcing them. This is the case the students reported."""
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")
    student_id = models.create_student("Alex", "Schueler", "gate1", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    a = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    b = models.create_task("Thema B", "", "", "MBI", "5", "pflicht")
    gate_id = models.create_subtask(a, "Abgabe", reihenfolge=1,
                                    artifact_gate_json=json.dumps(GATE_CONFIG))
    models.set_topic_queue(klasse_id, [a, b])
    models.assign_task_to_student(student_id, klasse_id, a)
    student_task = models.get_student_task(student_id, klasse_id)

    _login(client, student_id)
    failed = client.post(
        "/schueler/thema/thema-a/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(make_docx(FAIL_BODY)), "Abgabe.docx")},
        content_type="multipart/form-data",
    ).get_json()
    assert failed["passed"] is False

    models.toggle_student_subtask(student_task["id"], gate_id, True)
    page = client.get("/schueler/thema/thema-a").get_data(as_text=True)
    assert "Nächstes Thema starten" in page, \
        "a failing artifact check must not lock the student inside a finished unit"
