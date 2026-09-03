"""An artifact gate reports; it does not block.

Since 2026-09-03 every artifact check is a hint: a failing gate leaves the completion
checkbox live and does not hold the Thema open. What it still must do is describe the
file that is actually stored, and keep the attempt on record for the teacher.

The three defects this file was written for (2026-08-30) are still guarded, two of them
inverted by the policy change:

1. The completion zone used to be withheld only when `inline_gate` was set, but 5 of 6
   production gates are capstone gates -- so the guard short-circuited to "allowed".
   The guard is gone entirely now, and these tests pin that it stays gone on BOTH paths
   rather than coming back for one of them.
2. student_artifact_gate_check() refused to persist a failing re-check once the gate had
   passed, so the card described a file that had since been replaced. Still guarded --
   _save_artifact_file keeps the LATEST file, and the verdict has to follow it.
3. check_task_completion() ignored artifact_gate_passed. It now ignores it deliberately,
   which is a different thing from ignoring it by accident: the test says so out loud.
"""
import io
import json
import config
import models

from tests.test_artifact_extraction import make_docx

GATE_CONFIG = {"format": [".docx"], "required_text": ["Fachraumregeln"]}

PASS_BODY = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
             '<w:r><w:t>Fachraumregeln</w:t></w:r></w:p>')
FAIL_BODY = '<w:p><w:r><w:t>Nichts davon steht hier.</w:t></w:r></w:p>'


def _capstone_setup(app, tmp_path, username):
    """One Aufgabe carrying the gate -> it is the last one -> capstone path."""
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Alex", "Schueler", username, "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    gate_id = models.create_subtask(
        task_id, "Abgabe", reihenfolge=1,
        artifact_gate_json=json.dumps(GATE_CONFIG),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    student_task = models.get_student_task(student_id, klasse_id)
    return student_id, klasse_id, task_id, gate_id, student_task["id"]


def _upload(client, body):
    return client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(make_docx(body)), "Abgabe.docx")},
        content_type="multipart/form-data",
    )


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


# --- 1. a failing gate leaves the checkbox live, on both gate paths ---

def test_failing_capstone_gate_leaves_the_checkbox_live(app, client, tmp_path):
    """The student decides when to move on; the check only tells them what it saw."""
    student_id, *_ = _capstone_setup(app, tmp_path, "capstone1")
    _login(client, student_id)

    assert _upload(client, FAIL_BODY).get_json()["passed"] is False
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert 'id="completion-zone"' in page
    assert '<div id="completion-zone" hidden' not in page, \
        "an artifact check must not withhold the completion checkbox"


def test_passing_capstone_gate_leaves_the_checkbox_live(app, client, tmp_path):
    student_id, *_ = _capstone_setup(app, tmp_path, "capstone2")
    _login(client, student_id)

    assert _upload(client, PASS_BODY).get_json()["passed"] is True
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert 'id="completion-zone"' in page
    assert '<div id="completion-zone" hidden' not in page


def test_the_page_never_ships_a_hidden_completion_zone(app, client, tmp_path):
    """The old guard hid the zone server-side and JS handed it back. Both are gone --
    if either returns, a failing upload strands the student with no way forward."""
    student_id, *_ = _capstone_setup(app, tmp_path, "capstone3")
    _login(client, student_id)
    _upload(client, FAIL_BODY)

    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert "setCompletionZoneVisible" not in page
    assert "artifactGateRequired" not in page


# --- 2. the verdict follows the stored file ---

def test_failing_reupload_takes_the_pass_back(app, client, tmp_path):
    """The stored file is always the latest one. The verdict has to describe THAT file."""
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "reupload1")
    _login(client, student_id)

    assert _upload(client, PASS_BODY).get_json()["passed"] is True
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert 'class="gate-card mt-2 gate-passed"' in page

    assert _upload(client, FAIL_BODY).get_json()["passed"] is False
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert 'class="gate-card mt-2 gate-passed"' not in page, \
        "the card kept a stale green header above a fresh list of errors"
    assert 'class="gate-card mt-2 gate-ready"' in page


# --- 3. an unpassed gate does not hold the Thema open ---

def test_thema_completes_although_the_gate_failed(app, client, tmp_path):
    """Deliberate, not an oversight: the check advises, the student's tick decides."""
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "completion1")
    _login(client, student_id)
    _upload(client, FAIL_BODY)

    models.toggle_student_subtask(student_task_id, gate_id, True)
    assert models.check_task_completion(student_task_id) is True


def test_thema_completes_when_the_gate_passes(app, client, tmp_path):
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "completion2")
    _login(client, student_id)
    _upload(client, PASS_BODY)

    models.toggle_student_subtask(student_task_id, gate_id, True)
    assert models.check_task_completion(student_task_id) is True


def test_an_unticked_aufgabe_still_holds_the_thema_open(app, client, tmp_path):
    """Dropping the gate condition must not have dropped the completion check with it."""
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "completion3")
    _login(client, student_id)
    _upload(client, PASS_BODY)

    assert models.check_task_completion(student_task_id) is False


def test_the_failed_attempt_stays_on_record_for_the_teacher(app, client, tmp_path):
    """Nothing blocks any more, so the log is the only thing that remembers."""
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "record1")
    _login(client, student_id)
    _upload(client, FAIL_BODY)
    models.toggle_student_subtask(student_task_id, gate_id, True)

    attempts = models.get_artifact_gate_attempts_for_student(student_id)
    assert any(not a["passed"] for a in attempts)
