"""Regression tests: an upload endpoint the browser reads as JSON must fail as JSON.

Both an oversize upload and an unexpected crash used to land in the global
handlers, which flash + redirect. The student's fetch() then received a 302 with
an HTML body and no error text, so the page simply went quiet -- the failure
mode for a photo-heavy .pptx over MAX_CONTENT_LENGTH.
"""
import io
import json

import config
import models
import artifact_checker


def _student_with_gate(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    sid = models.create_student("Test", "Kind", "errshape", "pw123")
    kid = models.create_klasse("K")
    models.add_student_to_klasse(sid, kid)
    tid = models.create_task("Probethema", "", "", "MBI", "5", "pflicht")
    models.create_subtask(tid, "### CP", reihenfolge=1,
                          artifact_gate_json=json.dumps({"format": [".docx"]}))
    models.assign_task_to_student(sid, kid, tid)
    return sid


def test_oversize_upload_returns_json(client, app, tmp_path):
    sid = _student_with_gate(app, tmp_path)
    with client.session_transaction() as s:
        s["student_id"] = sid
    app.config["MAX_CONTENT_LENGTH"] = 1024
    try:
        r = client.post("/schueler/thema/probethema/aufgabe-1/abgabe-pruefen",
                        data={"file": (io.BytesIO(b"x" * 5000), "gross.docx")},
                        content_type="multipart/form-data")
        assert r.status_code == 413
        assert "zu groß" in r.get_json()["error"]
    finally:
        app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH


def test_oversize_form_upload_still_redirects(as_admin, app, tmp_path):
    """Non-AJAX uploads keep the flash + redirect they are written for."""
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    app.config["WTF_CSRF_ENABLED"] = False
    task_id = models.create_task("T", "", "", "MBI", "5", "pflicht")
    app.config["MAX_CONTENT_LENGTH"] = 1024
    try:
        r = as_admin.post(f"/admin/thema/{task_id}/material-upload",
                          data={"file": (io.BytesIO(b"x" * 5000), "gross.pdf")},
                          content_type="multipart/form-data")
        assert r.status_code == 302
    finally:
        app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH


def test_unexpected_crash_returns_json(client, app, tmp_path, monkeypatch):
    from tests.test_content_sniffing import DOCX
    sid = _student_with_gate(app, tmp_path)
    with client.session_transaction() as s:
        s["student_id"] = sid

    def boom(*a, **kw):
        raise RuntimeError("kaputt")

    # Something below the route blows up in a way nobody anticipated.
    monkeypatch.setattr(artifact_checker, "check_gate", boom)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        r = client.post("/schueler/thema/probethema/aufgabe-1/abgabe-pruefen",
                        data={"file": (io.BytesIO(DOCX), "meins.docx")},
                        content_type="multipart/form-data")
        # The route's own guard catches this one as a 400; either way the student
        # gets JSON with a message, never a redirect to the dashboard.
        assert r.status_code in (400, 500)
        assert r.is_json and r.get_json().get("error")
    finally:
        app.config.pop("PROPAGATE_EXCEPTIONS", None)
