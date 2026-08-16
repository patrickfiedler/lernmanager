"""Regression tests: zip-slip guard in topic-import material extraction.

Zip entry names aren't restricted by the format, so a crafted material
'pfad' plus a matching entry name can point outside UPLOAD_FOLDER unless
explicitly rejected. Covers both extraction code paths (app.py's web
import flow and import_task.py's CLI importer), which duplicate the logic.
"""
import io
import zipfile

import config
import app as app_module
from import_task import extract_zip_materials


def _make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf


def test_cli_importer_rejects_traversal_pfad(tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    outside_target = tmp_path / "outside.txt"
    config.UPLOAD_FOLDER = str(upload_root)

    traversal_name = "../outside.txt"
    zip_path = tmp_path / "evil.zip"
    with open(zip_path, 'wb') as f:
        f.write(_make_zip({traversal_name: b"payload"}).read())

    task_data = {"task": {"materials": [{"typ": "datei", "pfad": traversal_name}]}}
    extracted = extract_zip_materials(str(zip_path), task_data)

    assert extracted == []
    assert not outside_target.exists()


def test_cli_importer_still_extracts_legit_pfad(tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    config.UPLOAD_FOLDER = str(upload_root)

    zip_path = tmp_path / "ok.zip"
    with open(zip_path, 'wb') as f:
        f.write(_make_zip({"arbeitsblatt.pdf": b"payload"}).read())

    task_data = {"task": {"materials": [{"typ": "datei", "pfad": "arbeitsblatt.pdf"}]}}
    extracted = extract_zip_materials(str(zip_path), task_data)

    assert extracted == ["arbeitsblatt.pdf"]
    assert (upload_root / "arbeitsblatt.pdf").read_bytes() == b"payload"


def test_web_importer_rejects_traversal_pfad(tmp_path):
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    outside_target = tmp_path / "outside.txt"
    config.UPLOAD_FOLDER = str(upload_root)
    app_module._IMPORT_TMP_DIR = str(tmp_path / "import_tmp")

    traversal_name = "../outside.txt"
    tmp_id = app_module._save_import_zip(_make_zip({traversal_name: b"payload"}).read())
    task_list = [{"task": {"materials": [{"typ": "datei", "pfad": traversal_name}]}}]

    extracted = app_module._extract_import_zip_files(tmp_id, task_list)

    assert extracted == []
    assert not outside_target.exists()
