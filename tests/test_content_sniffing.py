"""Regression tests: an upload's content has to agree with its name.

The extension decides what may be stored and how it is served, so a renamed
file picks a rule meant for something else. docx/pptx/odt/odp/sb3 are all ZIP
containers -- magic bytes alone cannot separate them, which is why sniff_type
reads a marker entry out of the container.
"""
import io
import json
import zipfile

import config
import models
from utils import sniff_type, content_matches_extension

PY_SCRIPT = b"#!/usr/bin/env python\nimport os\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


# Valid enough to be parsed, not only recognised: artifact_processor reads
# word/document.xml with ElementTree, so the namespace has to be declared.
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCUMENT_XML = (
    f'<w:document xmlns:w="{_W}"><w:body>'
    '<w:p><w:r><w:t>Hallo Welt, das ist mein Dokument.</w:t></w:r></w:p>'
    '</w:body></w:document>'
)
DOCX = _zip({"word/document.xml": _DOCUMENT_XML, "[Content_Types].xml": "<x/>"})
PPTX = _zip({"ppt/presentation.xml": "<p:presentation/>", "[Content_Types].xml": "<x/>"})
SB3 = _zip({"project.json": '{"targets": []}'})
ODT = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": "<x/>"})
ODP = _zip({"mimetype": "application/vnd.oasis.opendocument.presentation", "content.xml": "<x/>"})
PLAIN_ZIP = _zip({"readme.txt": "hello"})


def test_sniff_images_and_pdf():
    assert sniff_type(PNG) == "png"
    assert sniff_type(GIF) == "gif"
    assert sniff_type(JPG) == "jpg"
    assert sniff_type(PDF) == "pdf"


def test_pdf_tolerates_preamble_bytes():
    """Real PDFs out of Word and from scanners carry bytes before %PDF-."""
    assert sniff_type(b"\n\n   " + PDF) == "pdf"
    assert sniff_type(b"x" * 900 + PDF) == "pdf"
    assert sniff_type(b"x" * 2000 + PDF) is None  # beyond the 1 KB window


def test_sniff_separates_the_zip_family():
    assert sniff_type(DOCX) == "docx"
    assert sniff_type(PPTX) == "pptx"
    assert sniff_type(SB3) == "sb3"
    assert sniff_type(ODT) == "odt"
    assert sniff_type(ODP) == "odp"
    assert sniff_type(PLAIN_ZIP) == "zip"


def test_sniff_unknown_content_is_none():
    assert sniff_type(PY_SCRIPT) is None
    assert sniff_type(b"") is None
    assert sniff_type(b"PK\x03\x04 truncated") is None  # broken zip, not a claim


def test_match_accepts_agreement_and_jpeg_spelling():
    assert content_matches_extension("a.pdf", PDF) == (True, "pdf")
    assert content_matches_extension("a.jpeg", JPG)[0]
    assert content_matches_extension("a.jpg", JPG)[0]
    assert content_matches_extension("Vorlage.docx", DOCX)[0]


def test_match_rejects_disagreement():
    ok, sniffed = content_matches_extension("Vorlage.docx", PPTX)
    assert not ok and sniffed == "pptx"
    ok, sniffed = content_matches_extension("bild.png", PDF)
    assert not ok and sniffed == "pdf"


def test_match_is_lenient_where_it_cannot_know():
    # Unrecognised content is not a mismatch -- the whitelist already decided
    # which extensions may be stored.
    assert content_matches_extension("a.docx", PY_SCRIPT) == (True, None)
    # A .zip legitimately contains anything, including an OOXML-looking tree.
    assert content_matches_extension("bundle.zip", DOCX)[0]


def _setup(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    return models.create_task("T", "", "", "MBI", "5", "pflicht")


def test_manual_upload_rejects_renamed_file(as_admin, app, tmp_path):
    task_id = _setup(app, tmp_path)
    r = as_admin.post(f"/admin/thema/{task_id}/material-upload",
                      data={"file": (io.BytesIO(PPTX), "Vorlage.docx")},
                      content_type="multipart/form-data", follow_redirects=True)
    assert "passt nicht zur Dateiendung" in r.get_data(as_text=True)
    assert models.get_materials(task_id) == []


def test_manual_upload_accepts_honest_file(as_admin, app, tmp_path):
    task_id = _setup(app, tmp_path)
    as_admin.post(f"/admin/thema/{task_id}/material-upload",
                  data={"file": (io.BytesIO(DOCX), "Vorlage.docx")},
                  content_type="multipart/form-data", follow_redirects=True)
    assert len(models.get_materials(task_id)) == 1


def test_zip_import_preview_rejects_renamed_material(as_admin, app, tmp_path):
    _setup(app, tmp_path)
    task = {"tasks": [{
        "name": "ZipThema", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg"}],
        "materials": [{"typ": "datei", "pfad": "Vorlage.docx", "beschreibung": "v"}],
    }]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("task.json", json.dumps(task))
        zf.writestr("Vorlage.docx", PPTX)   # actually a pptx
    buf.seek(0)
    r = as_admin.post("/admin/themen/import",
                      data={"action": "preview", "json_file": (buf, "bundle.zip")},
                      content_type="multipart/form-data")
    body = r.get_data(as_text=True)
    assert "in Wirklichkeit eine PPTX-Datei" in body
    assert 'name="zip_tmp_id"' not in body


def _student_with_gate(app, tmp_path, gate):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    sid = models.create_student("Test", "Kind", "sniffprobe", "pw123")
    kid = models.create_klasse("K")
    models.add_student_to_klasse(sid, kid)
    tid = models.create_task("Probethema", "", "", "MBI", "5", "pflicht")
    models.create_subtask(tid, "### CP", reihenfolge=1,
                          artifact_gate_json=json.dumps(gate))
    models.assign_task_to_student(sid, kid, tid)
    return sid


def test_gate_names_the_real_format_instead_of_a_parse_error(client, app, tmp_path):
    sid = _student_with_gate(app, tmp_path, {"format": [".docx", ".odt"], "min_words": 1})
    with client.session_transaction() as s:
        s["student_id"] = sid
    r = client.post("/schueler/thema/probethema/aufgabe-1/abgabe-pruefen",
                    data={"file": (io.BytesIO(PPTX), "Meins.docx")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "PPTX-Datei" in r.get_json()["error"]
    # Nothing stored: the upload never described a valid submission
    import os
    artefakte = os.path.join(config.UPLOAD_FOLDER, "artefakte")
    assert not os.path.isdir(artefakte) or os.listdir(artefakte) == []
