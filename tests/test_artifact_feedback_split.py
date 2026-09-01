"""Regression: the deterministic filename check must run independently of the
class's LLM-feedback toggle. Previously `check_filename()` was called from inside
the same `if llm_artifact_feedback_enabled:` block as the LLM criteria call in both
the gate route and the standalone feedback route -- so disabling LLM feedback for a
class silently disabled the (free, non-LLM) filename check too. See
_build_level2_feedback() in app.py.
"""
import io
import json
import config
import models
from tests.test_content_sniffing import DOCX

# A checkable format: check_gate fails closed on anything it cannot inspect
# (see tests/test_gate_fails_closed.py), so a .txt gate no longer passes.
GATE_CONFIG = {"format": [".docx"]}
GRADED_CONFIG = {
    "format": [".docx"],
    "expected_filename": "Abgabe-Alex",
    "criteria": ["Enthaelt eine Einleitung"],
}


def _student_with_graded_gate(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Alex", "Schueler", "artifacttest2", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Aufgabe mit Abgabe-Pruefung", reihenfolge=1,
        artifact_gate_json=json.dumps(GATE_CONFIG),
        graded_artifact_json=json.dumps(GRADED_CONFIG),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, klasse_id, task_id, subtask_id


def test_gate_check_filename_feedback_runs_with_llm_disabled(app, client, tmp_path):
    """klasse.llm_artifact_feedback_enabled defaults to 0 -- filename check must
    still appear in the chained Level-2 feedback."""
    student_id, klasse_id, task_id, subtask_id = _student_with_graded_gate(app, tmp_path)
    assert not models.get_klasse(klasse_id)["llm_artifact_feedback_enabled"]

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(DOCX), "Abgabe-Alex.docx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["passed"] is True
    assert body.get("llm_feedback"), "filename check should still run when LLM feedback is disabled"
    assert len(body["llm_feedback"]) == 1
    item = body["llm_feedback"][0]
    assert item["source"] == "deterministic"
    assert item["passed"] is True


def test_standalone_feedback_llm_disabled_still_checks_filename(app, client, tmp_path):
    student_id, klasse_id, task_id, subtask_id = _student_with_graded_gate(app, tmp_path)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.post(
        "/schueler/thema/testthema/aufgabe-1/artefakt/feedback",
        json={"text": "Anonymisierter Text der Abgabe.", "filename": "Abgabe-Alex.txt"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["llm_disabled"] is True
    assert body["feedback"], "filename check should still run when LLM feedback is disabled"
    assert len(body["feedback"]) == 1
    assert body["feedback"][0]["source"] == "deterministic"


def test_standalone_feedback_llm_enabled_keeps_filename_check(app, client, tmp_path):
    """With LLM feedback enabled, filename check must still be present alongside
    (an empty, since config.LLM_ENABLED=False in tests) LLM criteria result."""
    student_id, klasse_id, task_id, subtask_id = _student_with_graded_gate(app, tmp_path)
    models.set_klasse_llm_feedback(klasse_id, True)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.post(
        "/schueler/thema/testthema/aufgabe-1/artefakt/feedback",
        json={"text": "Anonymisierter Text der Abgabe.", "filename": "Abgabe-Alex.txt"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["llm_disabled"] is False
    assert len(body["feedback"]) == 1
    assert body["feedback"][0]["source"] == "deterministic"
