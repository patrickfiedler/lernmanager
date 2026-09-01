"""Regression tests: how a stored material is served back.

Accepting a file and displaying it are two decisions. A document format we
never render must arrive as a download, and no response may invite the browser
to guess a type other than the one we declared.
"""
import io

import config
import models
from tests.test_content_sniffing import PDF, PNG, JPG, DOCX, PPTX, SB3, PLAIN_ZIP

# Real bytes per format: an inline-served format must prove what it is
# (tests/test_content_sniffing.py::test_inline_formats_must_prove_what_they_are).
BYTES_FOR = {
    "pdf": PDF, "png": PNG, "jpg": JPG, "jpeg": JPG,
    "docx": DOCX, "pptx": PPTX, "sb3": SB3, "zip": PLAIN_ZIP,
}


def _upload(as_admin, task_id, name, data=None):
    data = data if data is not None else BYTES_FOR[name.rsplit(".", 1)[1].lower()]
    as_admin.post(f"/admin/thema/{task_id}/material-upload",
                  data={"file": (io.BytesIO(data), name)},
                  content_type="multipart/form-data", follow_redirects=True)
    return next(m for m in models.get_materials(task_id) if m["pfad"].endswith(name))


def _setup(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    return models.create_task("T", "", "", "MBI", "5", "pflicht")


def test_viewable_formats_stay_inline(as_admin, app, tmp_path):
    task_id = _setup(app, tmp_path)
    for name in ["skript.pdf", "bild.png", "foto.jpg"]:
        mat = _upload(as_admin, task_id, name)
        r = as_admin.get(f"/material/{mat['id']}/download")
        assert r.status_code == 200
        assert "attachment" not in (r.headers.get("Content-Disposition") or "")


def test_document_formats_are_forced_downloads(as_admin, app, tmp_path):
    task_id = _setup(app, tmp_path)
    for name in ["Vorlage.docx", "folien.pptx", "bundle.zip", "projekt.sb3"]:
        mat = _upload(as_admin, task_id, name)
        r = as_admin.get(f"/material/{mat['id']}/download")
        assert r.status_code == 200
        assert "attachment" in (r.headers.get("Content-Disposition") or ""), name


def test_nosniff_on_every_response(as_admin, app, tmp_path):
    task_id = _setup(app, tmp_path)
    mat = _upload(as_admin, task_id, "skript.pdf")
    for url in ["/login", f"/admin/thema/{task_id}", f"/material/{mat['id']}/download"]:
        r = as_admin.get(url)
        assert r.headers.get("X-Content-Type-Options") == "nosniff", url


def test_accel_redirect_marks_documents_as_attachment(as_admin, app, tmp_path):
    """Production path: nginx serves the bytes, so the disposition has to ride
    on the X-Accel-Redirect response instead of send_from_directory."""
    task_id = _setup(app, tmp_path)
    doc = _upload(as_admin, task_id, "Vorlage.docx")
    pdf = _upload(as_admin, task_id, "skript.pdf")
    app.debug = False
    try:
        r = as_admin.get(f"/material/{doc['id']}/download",
                         headers={"X-Forwarded-For": "1.2.3.4"})
        assert r.headers.get("X-Accel-Redirect")
        assert "attachment" in (r.headers.get("Content-Disposition") or "")

        r = as_admin.get(f"/material/{pdf['id']}/download",
                         headers={"X-Forwarded-For": "1.2.3.4"})
        assert r.headers.get("X-Accel-Redirect")
        assert "attachment" not in (r.headers.get("Content-Disposition") or "")
    finally:
        app.debug = True
