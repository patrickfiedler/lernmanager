"""Tests for the derived report files (grades.csv, summary.md, print slips)
the grading service produces and Lernmanager copies at import time --
models._copy_grading_reports and the download route it feeds.

The copy has to happen at import: purge_grading_run_media() fires
DELETE /jobs/<id> as soon as a run settles, which is *after* review, so
there is nothing left on the grading host by the time a teacher wants to
print slips.
"""
import io
import json
import os
import re

import config
import models


def _setup_run(job_id="job-rep-1"):
    klasse_id = models.create_klasse("6a")
    task_id = models.create_task("unit-3-bilder", "desc", "lz", "MBI", "6", "pflicht")
    models.create_student("Mueller", "Anna", f"u{job_id}", "pw", netzwerk_id="mueller.anna")
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "unit-3-bilder", "ollama", None)
    return run_id


class _FakeService:
    """Stands in for urllib against the grading host: a listing endpoint plus
    the file bytes, so no test needs a live M920x."""

    def __init__(self, files, fail_on=()):
        self.files = files
        self.fail_on = set(fail_on)
        self.requested = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.requested.append(url)
        if url.endswith("/files"):
            body = json.dumps({
                "job_id": "x",
                "files": [{"name": n, "size": len(b)} for n, b in self.files.items()],
            }).encode()
        else:
            name = url.rsplit("/", 1)[-1]
            if name in self.fail_on or name not in self.files:
                raise OSError("service went away")
            body = self.files[name]

        class _Resp:
            def read(self_inner):
                return body

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _Resp()


def _patch_service(monkeypatch, fake):
    monkeypatch.setattr(config, "GRADING_SERVICE_URL", "http://10.8.0.3:8420")
    monkeypatch.setattr(config, "GRADING_SERVICE_TOKEN", "tok")
    monkeypatch.setattr(models.urllib.request, "urlopen", fake)


def test_copy_grading_reports_stores_files(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()
    fake = _FakeService({
        "grades.csv": b"Student_ID,Total_Score\nmueller.anna,2\n",
        "summary.md": b"# Grading Summary Report\n",
        "print_slips.html": b"<html>slips</html>",
    })
    _patch_service(monkeypatch, fake)

    stored = models._copy_grading_reports(run_id, "job-rep-1")

    assert sorted(stored) == ["grades.csv", "print_slips.html", "summary.md"]
    reports = models.list_grading_reports(run_id)
    assert [r["name"] for r in reports] == ["grades.csv", "summary.md", "print_slips.html"]
    assert reports[0]["label"].endswith("Notenliste (CSV)")
    on_disk = os.path.join(models._grading_reports_dir(run_id), "summary.md")
    assert open(on_disk, "rb").read() == b"# Grading Summary Report\n"


def test_copy_grading_reports_ignores_files_outside_the_whitelist(db, tmp_path, monkeypatch):
    """The listing comes from another host. A name we did not ask for must not
    reach the filesystem, whatever it is called."""
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()
    fake = _FakeService({
        "grades.csv": b"ok",
        "run.log": b"internal",
        "../../escape.txt": b"nope",
    })
    _patch_service(monkeypatch, fake)

    stored = models._copy_grading_reports(run_id, "job-rep-1")

    assert stored == ["grades.csv"]
    assert os.listdir(models._grading_reports_dir(run_id)) == ["grades.csv"]
    assert not os.path.exists(tmp_path / "escape.txt")


def test_copy_grading_reports_survives_an_offline_service(db, tmp_path, monkeypatch):
    """Grades already imported fine; a missing report must not raise."""
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()

    def _boom(req, timeout=None):
        raise OSError("wireguard down")

    _patch_service(monkeypatch, _boom)
    assert models._copy_grading_reports(run_id, "job-rep-1") == []
    assert models.list_grading_reports(run_id) == []


def test_copy_grading_reports_keeps_what_it_could_fetch(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()
    fake = _FakeService(
        {"grades.csv": b"ok", "summary.md": b"also ok"}, fail_on={"summary.md"},
    )
    _patch_service(monkeypatch, fake)

    assert models._copy_grading_reports(run_id, "job-rep-1") == ["grades.csv"]


def test_purge_deletes_media_but_keeps_reports(db, tmp_path, monkeypatch):
    """Both halves matter: a purge that stopped deleting anything would still
    pass a test that only checked reports/ survived."""
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(config, "GRADING_SERVICE_URL", "")  # skip the remote DELETE leg
    run_id = _setup_run()

    run_dir = os.path.join(models._grading_upload_dir(), str(run_id))
    media_dir = os.path.join(run_dir, "mueller.anna")
    os.makedirs(media_dir)
    with open(os.path.join(media_dir, "001.jpg"), "wb") as f:
        f.write(b"\xff\xd8\xff")
    os.makedirs(models._grading_reports_dir(run_id))
    with open(os.path.join(models._grading_reports_dir(run_id), "grades.csv"), "wb") as f:
        f.write(b"Student_ID\n")

    models.purge_grading_run_media(run_id)

    assert not os.path.exists(media_dir)
    assert [r["name"] for r in models.list_grading_reports(run_id)] == ["grades.csv"]


def test_corrected_count_reflects_overridden_criteria(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()
    student_id = models.get_student_by_netzwerk_id("mueller.anna")
    task_id = models.get_grading_run(run_id)["task_id"]

    result_id = models.create_grading_result(
        grading_run_id=run_id, task_id=task_id, student_id=student_id,
        netzwerk_id="mueller.anna",
        criteria=[
            {"name": "Titelfolie", "score": 1, "max_score": 1, "feedback": "ok"},
            {"name": "Pixel-Bild", "score": 0, "max_score": 3, "feedback": "fehlt"},
        ],
        llm_total_score=1, llm_max_score=4,
    )
    assert models.count_grading_results_corrected(run_id) == 0

    # Teacher raises one criterion -- save_grading_result_review marks it
    # overridden, which is what the staleness warning keys on.
    criteria = models.get_grading_result(result_id)["criteria"]
    for c in criteria:
        if c["name"] == "Pixel-Bild":
            c["teacher_score"] = 3
    models.save_grading_result_review(result_id, criteria)

    assert models.count_grading_results_corrected(run_id) == 1


def test_download_route_refuses_unlisted_names(as_admin, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()
    os.makedirs(models._grading_reports_dir(run_id))
    with open(os.path.join(models._grading_reports_dir(run_id), "grades.csv"), "wb") as f:
        f.write(b"Student_ID\n")

    ok = as_admin.get(f"/admin/grading-run/{run_id}/bericht/grades.csv")
    assert ok.status_code == 200
    assert b"Student_ID" in ok.data

    for name in ("run.log", "summary.md"):  # not whitelisted / not on disk
        assert as_admin.get(f"/admin/grading-run/{run_id}/bericht/{name}").status_code == 404


def test_detail_page_renders_downloads_and_warns_only_when_corrected(as_admin, tmp_path, monkeypatch):
    """Renders the real page, not just the model call: the warning is the
    whole point of the section and it lives in the template."""
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path))
    run_id = _setup_run()
    os.makedirs(models._grading_reports_dir(run_id))
    for name in ("grades.csv", "print_slips.html"):
        with open(os.path.join(models._grading_reports_dir(run_id), name), "wb") as f:
            f.write(b"x")

    student_id = models.get_student_by_netzwerk_id("mueller.anna")
    task_id = models.get_grading_run(run_id)["task_id"]
    result_id = models.create_grading_result(
        grading_run_id=run_id, task_id=task_id, student_id=student_id,
        netzwerk_id="mueller.anna",
        criteria=[{"name": "Pixel-Bild", "score": 0, "max_score": 3, "feedback": "fehlt"}],
        llm_total_score=0, llm_max_score=3,
    )

    # Collapse whitespace: the browser does, so an assertion on the exact
    # source layout would fail on a harmless reflow of the template.
    def _text(resp):
        return re.sub(r"\s+", " ", resp.get_data(as_text=True))

    page = _text(as_admin.get(f"/admin/grading-run/{run_id}"))
    assert "Bewertungsdateien" in page
    assert f"/admin/grading-run/{run_id}/bericht/grades.csv" in page
    assert "Notenliste (CSV)" in page
    assert "korrigiert" not in page  # nothing overridden yet

    criteria = models.get_grading_result(result_id)["criteria"]
    criteria[0]["teacher_score"] = 3
    models.save_grading_result_review(result_id, criteria)

    page = _text(as_admin.get(f"/admin/grading-run/{run_id}"))
    assert "1 Ergebnis wurde nach dem Erstellen der Zettel korrigiert" in page
