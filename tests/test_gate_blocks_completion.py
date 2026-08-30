"""A failing artifact gate must not sit under a live completion checkbox.

Found in production 2026-08-30 from a screenshot: a deliberately failing upload on
"Startklar im Fachraum" showed a green "📎 Abgabe geprüft ✓ — Deine Datei wurde
erfolgreich geprüft" header, a live "Ich habe das geschafft!" checkbox one click from
the Aufgaben-Quiz, and -- two sections further down -- the real result, five errors and
two warnings. Three separate defects, one screen:

1. templates/student/klasse.html tested `inline_gate` only when deciding whether to
   render the completion zone. 5 of the 6 gates in production are CAPSTONE gates, where
   `inline_gate` is None, so the guard short-circuited to "allowed" and never fired.
2. student_artifact_gate_check() refused to persist a failing re-check once the gate had
   passed ("if not already_passed or result['passed']"), so the card header described an
   upload that had since been replaced -- _save_artifact_file keeps the LATEST file, not
   the latest passing one.
3. check_task_completion() never looked at artifact_gate_passed, so a Thema closed on
   ticked boxes and passed quizzes alone -- contradicting the card's own promise that the
   file "muss geprüft sein, bevor du das Thema abschließen kannst".
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


def _capstone_setup(app, tmp_path, username, gate_required=True):
    """One Aufgabe carrying the gate -> it is the last one -> capstone path."""
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Alex", "Schueler", username, "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    if not gate_required:
        models.set_klasse_artifact_gate_required(klasse_id, False)
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


# --- 1. the checkbox is withheld on the capstone path, not just the inline one ---

def test_failing_capstone_gate_withholds_the_checkbox(app, client, tmp_path):
    student_id, *_ = _capstone_setup(app, tmp_path, "capstone1")
    _login(client, student_id)

    assert _upload(client, FAIL_BODY).get_json()["passed"] is False
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    # Rendered but hidden, so a passing re-check can reveal it without a reload.
    assert '<div id="completion-zone" hidden' in page, \
        "a failing capstone gate must not leave a live completion checkbox on the page"


def test_passing_capstone_gate_releases_the_checkbox(app, client, tmp_path):
    """The guard must not lock students out -- it lifts the moment the gate passes."""
    student_id, *_ = _capstone_setup(app, tmp_path, "capstone2")
    _login(client, student_id)

    assert _upload(client, PASS_BODY).get_json()["passed"] is True
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert 'id="completion-zone"' in page
    assert '<div id="completion-zone" hidden' not in page


def test_checkbox_stays_when_the_class_does_not_require_the_gate(app, client, tmp_path):
    """artifact_gate_required is the teacher's switch; off means advisory, as before."""
    student_id, *_ = _capstone_setup(app, tmp_path, "capstone3", gate_required=False)
    _login(client, student_id)

    assert _upload(client, FAIL_BODY).get_json()["passed"] is False
    page = client.get("/schueler/thema/testthema").get_data(as_text=True)
    assert 'id="completion-zone"' in page
    assert '<div id="completion-zone" hidden' not in page


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


# --- 3. an unpassed required gate blocks Thema completion ---

def test_thema_does_not_complete_while_the_gate_fails(app, client, tmp_path):
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "completion1")
    _login(client, student_id)
    _upload(client, FAIL_BODY)

    models.toggle_student_subtask(student_task_id, gate_id, True)
    assert models.check_task_completion(student_task_id) is False, \
        "the gate card promises the file must be checked before the Thema can close"


def test_thema_completes_once_the_gate_passes(app, client, tmp_path):
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "completion2")
    _login(client, student_id)
    _upload(client, PASS_BODY)

    models.toggle_student_subtask(student_task_id, gate_id, True)
    assert models.check_task_completion(student_task_id) is True


def test_gate_does_not_block_completion_when_the_class_switched_it_off(app, client, tmp_path):
    student_id, klasse_id, task_id, gate_id, student_task_id = _capstone_setup(
        app, tmp_path, "completion3", gate_required=False)
    _login(client, student_id)
    _upload(client, FAIL_BODY)

    models.toggle_student_subtask(student_task_id, gate_id, True)
    assert models.check_task_completion(student_task_id) is True
