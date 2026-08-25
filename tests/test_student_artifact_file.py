"""Regression tests: artifact uploads must persist to disk (latest version only,
overwritten on re-upload) instead of being discarded after text extraction.

Storage is keyed by (student, task/unit), not (student, subtask/checkpoint):
units use the "gradual artifact building" pattern (docs/shared/mbi/content-design.md)
-- one growing document uploaded fresh at each checkpoint, not a separate file per
checkpoint. The download route must only be reachable by the uploading student or
an admin.
"""
import io
import json
import config
import models

GATE_CONFIG = {"format": [".txt", ".md"]}


def _student_with_gated_subtask(app, tmp_path):
    """Single checkpoint task -- also exercises the capstone-gate render path."""
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Test", "Schueler", "artifacttest", "pw123")
    other_student_id = models.create_student("Andere", "Schuelerin", "otherstudent", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    models.add_student_to_klasse(other_student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Aufgabe mit Abgabe-Pruefung", reihenfolge=1,
        artifact_gate_json=json.dumps(GATE_CONFIG)
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    models.assign_task_to_student(other_student_id, klasse_id, task_id)
    return student_id, other_student_id, task_id, subtask_id


def _student_with_two_checkpoints(app, tmp_path):
    """Intro (position 1, always displayed as 'E', never gated) plus two checkpoints in the
    same unit, mirroring the real "mein-blog"/"bild-steckbrief" units: both accept the same
    growing document, not two independent files."""
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Test", "Schueler", "artifacttest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    models.create_subtask(task_id, "Einfuehrung", reihenfolge=1)
    subtask1_id = models.create_subtask(
        task_id, "Checkpoint 1", reihenfolge=2,
        artifact_gate_json=json.dumps(GATE_CONFIG)
    )
    subtask2_id = models.create_subtask(
        task_id, "Checkpoint 2", reihenfolge=3,
        artifact_gate_json=json.dumps(GATE_CONFIG),
        graded_artifact_json=json.dumps({"criteria": ["Titelfolie vorhanden", "Mindestens 3 Folien"]})
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, task_id, subtask1_id, subtask2_id


def test_gate_upload_saves_file_and_db_row(app, client, tmp_path):
    student_id, _, task_id, subtask_id = _student_with_gated_subtask(app, tmp_path)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(b"meine abgabe"), "abgabe.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["file_saved"] is True
    assert body["file_url"]

    record = models.get_student_artifact_file(student_id, task_id)
    assert record is not None
    assert record["original_filename"] == "abgabe.txt"
    assert record["disk_filename"] == f"{student_id}_{task_id}.txt"

    stored_path = tmp_path / "uploads" / "artefakte" / record["disk_filename"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"meine abgabe"

    # Topic page must render the download link without error (capstone gate
    # card here, since the only subtask is also the last one)
    page = client.get("/schueler/thema/testthema")
    assert page.status_code == 200
    assert b"abgabe.txt" in page.data
    assert f"/artefakt-datei/{student_id}/{task_id}/download".encode() in page.data


def test_admin_student_detail_shows_uploaded_file(app, client, tmp_path):
    student_id, _, task_id, subtask_id = _student_with_gated_subtask(app, tmp_path)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(b"meine abgabe"), "abgabe.txt")},
        content_type="multipart/form-data",
    )

    models.create_admin("testadmin", "testpass")
    with models.db_session() as conn:
        admin_id = conn.execute("SELECT id FROM admin WHERE username = 'testadmin'").fetchone()["id"]
    with client.session_transaction() as sess:
        sess.clear()
        sess["admin_id"] = admin_id

    page = client.get(f"/admin/schueler/{student_id}")
    assert page.status_code == 200
    assert b"abgabe.txt" in page.data
    assert f"/artefakt-datei/{student_id}/{task_id}/download".encode() in page.data


def test_reupload_with_different_extension_replaces_old_file(app, client, tmp_path):
    student_id, _, task_id, subtask_id = _student_with_gated_subtask(app, tmp_path)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(b"erste version"), "abgabe.txt")},
        content_type="multipart/form-data",
    )
    first_record = models.get_student_artifact_file(student_id, task_id)
    first_path = tmp_path / "uploads" / "artefakte" / first_record["disk_filename"]
    assert first_path.exists()

    client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(b"zweite version"), "abgabe.md")},
        content_type="multipart/form-data",
    )

    # Old .txt file must be gone -- no orphan left behind (latest-only retention)
    assert not first_path.exists()

    second_record = models.get_student_artifact_file(student_id, task_id)
    assert second_record["disk_filename"] == f"{student_id}_{task_id}.md"
    second_path = tmp_path / "uploads" / "artefakte" / second_record["disk_filename"]
    assert second_path.read_bytes() == b"zweite version"

    # Still exactly one row for this (student, task) -- overwrite, not append
    with models.db_session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM student_artifact_file WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        ).fetchone()[0]
    assert count == 1


def test_second_checkpoint_overwrites_first_checkpoints_file(app, client, tmp_path):
    """Core "gradual artifact building" behavior: checkpoint 2's upload replaces
    checkpoint 1's file (same growing document), not a second independent file --
    and checkpoint 1's own card, if revisited, must show the newer version too."""
    student_id, task_id, subtask1_id, subtask2_id = _student_with_two_checkpoints(app, tmp_path)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    client.post(
        "/schueler/thema/testthema/aufgabe-2/abgabe-pruefen",
        data={"file": (io.BytesIO(b"nach checkpoint 1"), "wachsende-datei.txt")},
        content_type="multipart/form-data",
    )
    first_record = models.get_student_artifact_file(student_id, task_id)
    first_path = tmp_path / "uploads" / "artefakte" / first_record["disk_filename"]
    assert first_path.read_bytes() == b"nach checkpoint 1"

    client.post(
        "/schueler/thema/testthema/aufgabe-3/abgabe-pruefen",
        data={"file": (io.BytesIO(b"nach checkpoint 2, laenger"), "wachsende-datei.txt")},
        content_type="multipart/form-data",
    )

    # Exactly one row for the whole unit -- not one per checkpoint
    with models.db_session() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM student_artifact_file WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        ).fetchone()[0]
    assert count == 1

    record = models.get_student_artifact_file(student_id, task_id)
    assert first_path.read_bytes() == b"nach checkpoint 2, laenger"  # same disk file, overwritten in place
    stored_path = tmp_path / "uploads" / "artefakte" / record["disk_filename"]
    assert stored_path.read_bytes() == b"nach checkpoint 2, laenger"

    # Viewing the unit at checkpoint 1's position shows the up-to-date (checkpoint 2) file
    page = client.get("/schueler/thema/testthema?aufgabe=2")
    assert page.status_code == 200
    assert f"/artefakt-datei/{student_id}/{task_id}/download".encode() in page.data

    # Fold-out states which checkpoint the file was last checked for (checkpoint 2 = "Aufgabe 2"),
    # and lists earlier checkpoints still structurally satisfied by the current file (checkpoint 1
    # = "Aufgabe 1") -- but not checkpoint 2 itself again, since its own criteria are shown right
    # below instead of a redundant/contradictory pass checkmark.
    body = page.get_data(as_text=True)
    assert "Aufgabe 1" in body
    assert "Aufgabe 2" in body
    # Criteria from the last checkpoint (checkpoint 2) are shown, plain text, no grading
    assert "Titelfolie vorhanden" in body
    assert "Mindestens 3 Folien" in body


def test_download_ownership_check(app, client, tmp_path):
    student_id, other_student_id, task_id, subtask_id = _student_with_gated_subtask(app, tmp_path)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(b"meine abgabe"), "abgabe.txt")},
        content_type="multipart/form-data",
    )

    download_url = f"/artefakt-datei/{student_id}/{task_id}/download"

    # Owner can download
    owner_resp = client.get(download_url)
    assert owner_resp.status_code == 200
    assert owner_resp.data == b"meine abgabe"

    # A different student is refused -- app-wide 403 handler redirects with a flash message
    with client.session_transaction() as sess:
        sess.clear()
        sess["student_id"] = other_student_id
    other_resp = client.get(download_url)
    assert other_resp.status_code == 302

    # No session at all is refused
    with client.session_transaction() as sess:
        sess.clear()
    anon_resp = client.get(download_url)
    assert anon_resp.status_code == 302

    # Admin can download
    models.create_admin("testadmin", "testpass")
    with models.db_session() as conn:
        admin_id = conn.execute("SELECT id FROM admin WHERE username = 'testadmin'").fetchone()["id"]
    with client.session_transaction() as sess:
        sess.clear()
        sess["admin_id"] = admin_id
    admin_resp = client.get(download_url)
    assert admin_resp.status_code == 200
