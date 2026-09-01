"""Regression tests: the on-disk name of a stored artifact is ours, not the
uploader's.

_save_artifact_file names files {student_id}_{task_id}{ext}. Only ext came from
the upload, so '..' could never be the first path component and the directory
was never escapable -- but the extension itself was attacker-chosen, and a null
byte or an odd double extension picked what we wrote to disk.
"""
import os

import config
import models
from app import _save_artifact_file, _artifact_upload_dir


def _fixture(tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")
    sid = models.create_student("A", "B", "storeprobe", "pw")
    kid = models.create_klasse("K")
    models.add_student_to_klasse(sid, kid)
    tid = models.create_task("T", "", "", "MBI", "5", "pflicht")
    stid = models.create_subtask(tid, "x", reihenfolge=1)
    models.assign_task_to_student(sid, kid, tid)
    return sid, tid, stid


def test_accepted_extension_is_kept(db, tmp_path):
    sid, tid, stid = _fixture(tmp_path)
    for name, expected in [("Meins.docx", ".docx"), ("Folien.PPTX", ".pptx"),
                           ("projekt.sb3", ".sb3")]:
        _save_artifact_file(sid, tid, stid, b"x", name)
        assert os.listdir(_artifact_upload_dir()) == [f"{sid}_{tid}{expected}"]


def test_unexpected_extension_becomes_bin(db, tmp_path):
    sid, tid, stid = _fixture(tmp_path)
    for name in ["x.php", "x.PhP", "x.html", "x.docx\x00.py", "noext", "x.tar.gz"]:
        _save_artifact_file(sid, tid, stid, b"x", name)
        assert os.listdir(_artifact_upload_dir()) == [f"{sid}_{tid}.bin"], name


def test_crafted_names_stay_inside_the_directory(db, tmp_path):
    """Names built to put a path separator into the extension must not write
    outside artefakte/ -- nor blow up the request."""
    sid, tid, stid = _fixture(tmp_path)
    for name in ["x.sb3/../../../pwn.txt",
                 "a.b/../../../../ESCAPED/pwn",
                 "q.p/../../ESCAPED2"]:
        _save_artifact_file(sid, tid, stid, b"x", name)
        written = {p.name for p in tmp_path.rglob("*") if p.is_file()}
        assert written <= {f"{sid}_{tid}.bin", "test.db"}, name

    # Nothing was created anywhere but inside the artefakte directory
    outside = [p for p in tmp_path.rglob("*")
               if p.is_file() and p.name != "test.db"
               and p.parent != tmp_path / "uploads" / "artefakte"]
    assert outside == []


def test_original_filename_is_still_what_the_student_downloads(db, tmp_path):
    """Pinning the disk name must not change the name the student gets back."""
    sid, tid, stid = _fixture(tmp_path)
    _save_artifact_file(sid, tid, stid, b"x", "Mein Steckbrief.docx")
    record = models.get_student_artifact_file(sid, tid)
    assert record["original_filename"] == "Mein Steckbrief.docx"
    assert record["disk_filename"] == f"{sid}_{tid}.docx"
