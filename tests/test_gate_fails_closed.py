"""Regression tests: a gate that cannot be checked must not pass anyone.

check_gate used to return passed=True for any format it did not recognise, so
a gate declaring .pdf/.txt -- or carrying no `format` key at all -- accepted
every file and, on an inline gate, auto-completed the Aufgabe. A checkpoint
that looks checked and is not is worse than one that visibly fails.
"""
import io
import json
import os

import pytest

import artifact_checker
import config
import import_task
import models


def test_checkable_formats_are_the_ones_dispatch_handles():
    assert set(artifact_checker.CHECKABLE_FORMATS) == {'.pptx', '.odp', '.docx', '.odt', '.sb3'}


def test_unknown_format_fails_closed():
    for filename in ["abgabe.pdf", "abgabe.txt", "abgabe.md", "abgabe", "abgabe.py"]:
        result = artifact_checker.check_gate(b"anything", filename, {"min_words": 1})
        assert result["passed"] is False, filename
        assert "Lehrkraft" in " ".join(result["details"]), filename


def test_import_rejects_gate_with_uncheckable_format():
    data = {"task": {
        "name": "T", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg",
                      "artifact_gate": {"format": [".pdf"], "min_words": 10}}],
    }}
    with pytest.raises(import_task.ValidationError) as e:
        import_task.validate_task_structure(data)
    assert "kann nicht geprüft werden" in str(e.value)
    assert ".pdf" in str(e.value)


def test_import_accepts_gate_with_checkable_format():
    data = {"task": {
        "name": "T", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg",
                      "artifact_gate": {"format": [".docx", ".odt"], "min_words": 10}}],
    }}
    import_task.validate_task_structure(data)  # must not raise


def test_import_flags_mixed_format_list():
    """One good entry does not excuse an uncheckable one -- the student who
    uploads the .pdf still hits the wall."""
    data = {"task": {
        "name": "T", "fach": "MBI", "stufe": "5", "beschreibung": "x",
        "subtasks": [{"beschreibung": "### A", "path": "wanderweg",
                      "artifact_gate": {"format": [".docx", ".pdf"]}}],
    }}
    with pytest.raises(import_task.ValidationError) as e:
        import_task.validate_task_structure(data)
    assert ".pdf" in str(e.value)


def _student_with_gate(app, tmp_path, gate, n_subtasks=1):
    app.config["WTF_CSRF_ENABLED"] = False
    up = str(tmp_path / "uploads")
    config.UPLOAD_FOLDER = up
    app.config["UPLOAD_FOLDER"] = up
    sid = models.create_student("Test", "Kind", "gateprobe", "pw123")
    kid = models.create_klasse("K")
    models.add_student_to_klasse(sid, kid)
    tid = models.create_task("Probethema", "", "", "MBI", "5", "pflicht")
    sub_ids = []
    for n in range(n_subtasks):
        sub_ids.append(models.create_subtask(
            tid, f"### CP{n+1}", reihenfolge=n + 1,
            artifact_gate_json=json.dumps(gate)))
    models.assign_task_to_student(sid, kid, tid)
    return sid, tid, sub_ids


def test_gate_without_format_no_longer_waves_anything_through(client, app, tmp_path):
    """The case that used to auto-complete an Aufgabe for a blank text file."""
    sid, tid, _ = _student_with_gate(app, tmp_path, {"min_words": 1}, n_subtasks=2)
    with client.session_transaction() as s:
        s["student_id"] = sid

    r = client.post("/schueler/thema/probethema/aufgabe-1/abgabe-pruefen",
                    data={"file": (io.BytesIO(b"nichts"), "leer.txt")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["passed"] is False

    # ...and the Aufgabe is not silently ticked off
    klasse_id = models.get_student_klassen(sid)[0]["id"]
    student_task = models.get_student_task(sid, klasse_id)
    progress = models.get_student_subtask_progress(student_task["id"])
    assert not progress[0]["erledigt"]


def test_working_gate_is_unaffected(client, app, tmp_path):
    """A .docx gate keeps checking .docx -- fail-closed must not become
    fail-always."""
    from tests.test_content_sniffing import DOCX
    sid, tid, _ = _student_with_gate(app, tmp_path, {"format": [".docx"], "min_words": 0})
    with client.session_transaction() as s:
        s["student_id"] = sid
    r = client.post("/schueler/thema/probethema/aufgabe-1/abgabe-pruefen",
                    data={"file": (io.BytesIO(DOCX), "Meins.docx")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["passed"] is True
