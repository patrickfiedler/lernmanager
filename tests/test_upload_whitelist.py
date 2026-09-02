"""Regression tests: one extension whitelist, enforced on every path that
writes into UPLOAD_FOLDER.

The ZIP import used to check nothing at all, so shipping a file inside a
bundle bypassed the manual upload's whitelist entirely -- and download_material
served the result inline on our own origin.
"""
import io
import json
import zipfile

import config
import models
import import_task
from utils import allowed_file, file_extension
from tests.test_content_sniffing import PDF, DOCX, PY_SCRIPT


def _bundle(materials, extra_entries):
    """A valid single-topic import ZIP carrying the given material entries."""
    task = {"tasks": [{
        "name": "ZipThema", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg"}],
        "materials": materials,
    }]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("task.json", json.dumps(task))
        for name, content in extra_entries.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf, task


def test_extension_helper():
    assert file_extension("a.DOCX") == "docx"
    assert file_extension("noext") == ""
    assert file_extension("a.tar.gz") == "gz"


def test_allowed_file_follows_config():
    assert allowed_file("skript.pdf")
    assert allowed_file("Vorlage.docx")      # template_material needs this
    assert allowed_file("praesentation.pptx")
    assert not allowed_file("payload.py")
    assert not allowed_file("evil.html")
    assert not allowed_file("boom.sh")
    assert not allowed_file("noextension")


def test_import_validation_rejects_disallowed_material(tmp_path):
    config.DATABASE = str(tmp_path / "t.db")
    models.init_db()
    data = {"task": {
        "name": "T", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg"}],
        "materials": [{"typ": "datei", "pfad": "evil.html", "beschreibung": "h"}],
    }}
    try:
        import_task.validate_task_structure(data)
        assert False, "expected ValidationError for evil.html"
    except import_task.ValidationError as e:
        assert "evil.html" in str(e)
        assert "nicht erlaubt" in str(e)


def test_import_validation_accepts_document_materials(tmp_path):
    config.DATABASE = str(tmp_path / "t.db")
    models.init_db()
    data = {"task": {
        "name": "T", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg"}],
        "materials": [{"typ": "datei", "pfad": "01_Startklar_Vorlage.docx", "beschreibung": "v"}],
    }}
    import_task.validate_task_structure(data)  # must not raise


def test_zip_import_web_refuses_bundle_with_script(as_admin, app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up

    buf, _ = _bundle(
        [{"typ": "datei", "pfad": "evil.html", "beschreibung": "h"}],
        {"evil.html": "<script>alert(1)</script>"},
    )
    r = as_admin.post("/admin/themen/import",
                      data={"action": "preview", "json_file": (buf, "bundle.zip")},
                      content_type="multipart/form-data")
    body = r.get_data(as_text=True)
    assert "nicht erlaubt" in body
    # No confirm form is offered for a rejected bundle
    assert 'name="zip_tmp_id"' not in body


def test_zip_extraction_skips_disallowed_even_if_validation_bypassed(tmp_path):
    """Defence in depth: extract_zip_materials must not write a file the
    download route would serve as text/html, whatever the caller validated."""
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")
    (tmp_path / "uploads").mkdir()
    zip_path = tmp_path / "b.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("evil.html", "<script>alert(1)</script>")
        zf.writestr("ok.pdf", "%PDF-1.4")
    task_data = {"task": {"materials": [
        {"typ": "datei", "pfad": "evil.html"},
        {"typ": "datei", "pfad": "ok.pdf"},
    ]}}
    extracted = import_task.extract_zip_materials(str(zip_path), task_data, task_id=7)
    assert extracted == ["ok.pdf"]
    assert not (tmp_path / "uploads" / "thema-7" / "evil.html").exists()
    assert (tmp_path / "uploads" / "thema-7" / "ok.pdf").exists()


def test_manual_upload_accepts_docx_and_rejects_script(as_admin, app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    task_id = models.create_task("T", "", "", "MBI", "5", "pflicht")

    for name, content in [("Vorlage.docx", DOCX), ("skript.pdf", PDF),
                          ("payload.py", PY_SCRIPT), ("evil.html", b"<h1>x</h1>")]:
        as_admin.post(f"/admin/thema/{task_id}/material-upload",
                      data={"file": (io.BytesIO(content), name)},
                      content_type="multipart/form-data", follow_redirects=True)
    stored = {m["pfad"] for m in models.get_materials(task_id)}
    assert stored == {f"thema-{task_id}/Vorlage.docx", f"thema-{task_id}/skript.pdf"}
