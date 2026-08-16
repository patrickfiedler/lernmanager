"""Tests for models._copy_grading_media -- downloading graded images from the
grading service at import time (teacher-review-ui.md §6: "Lernmanager copies
it at import" -- the source job's media is purged once reviewed, so this
can't happen lazily later). urllib.request.urlopen is mocked; no real network.
"""
import os
from unittest.mock import patch, MagicMock

import config
import models


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_copy_grading_media_downloads_and_rewrites_path(tmp_path, db):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    config.UPLOAD_FOLDER = str(tmp_path)

    media = [{"file": "media/mueller.anna/001.jpg", "kind": "image", "source": "Folie 1"}]

    with patch("models.urllib.request.urlopen", return_value=_FakeResponse(b"\xff\xd8\xff-fake")) as mock_open:
        copied = models._copy_grading_media(run_id=7, job_id="job-1", netzwerk_id="mueller.anna", media_list=media)

    assert len(copied) == 1
    assert copied[0]["file"] == "7/mueller.anna/001.jpg"
    assert copied[0]["source"] == "Folie 1"
    saved_path = os.path.join(str(tmp_path), "grading", "7", "mueller.anna", "001.jpg")
    assert os.path.isfile(saved_path)
    with open(saved_path, "rb") as f:
        assert f.read() == b"\xff\xd8\xff-fake"

    called_url = mock_open.call_args[0][0].full_url
    assert called_url == "http://10.8.0.3:8420/jobs/job-1/media/mueller.anna/001.jpg"
    assert mock_open.call_args[0][0].get_header("Authorization") == "Bearer test-token"


def test_copy_grading_media_skips_failed_download(tmp_path, db):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    config.UPLOAD_FOLDER = str(tmp_path)

    media = [
        {"file": "media/mueller.anna/001.jpg", "kind": "image"},
        {"file": "media/mueller.anna/002.jpg", "kind": "image"},
    ]

    def side_effect(req, timeout=None):
        if "001.jpg" in req.full_url:
            return _FakeResponse(b"ok")
        raise OSError("connection refused")

    with patch("models.urllib.request.urlopen", side_effect=side_effect):
        copied = models._copy_grading_media(run_id=7, job_id="job-1", netzwerk_id="mueller.anna", media_list=media)

    assert len(copied) == 1
    assert copied[0]["file"] == "7/mueller.anna/001.jpg"


def test_copy_grading_media_noop_when_service_not_configured(tmp_path, db):
    config.GRADING_SERVICE_URL = ""
    config.UPLOAD_FOLDER = str(tmp_path)
    media = [{"file": "media/mueller.anna/001.jpg", "kind": "image"}]
    assert models._copy_grading_media(run_id=7, job_id="job-1", netzwerk_id="mueller.anna", media_list=media) == []


def test_copy_grading_media_empty_list_noop(tmp_path, db):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.UPLOAD_FOLDER = str(tmp_path)
    assert models._copy_grading_media(run_id=7, job_id="job-1", netzwerk_id="mueller.anna", media_list=[]) == []


def test_copy_grading_media_rejects_path_traversal_in_netzwerk_id(tmp_path, db):
    """
    Security review 2026-08-16 finding #4: netzwerk_id comes straight from
    the callback payload's student_id -- a crafted or compromised callback
    must not be able to write outside instance/uploads/grading/.
    """
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    config.UPLOAD_FOLDER = str(tmp_path)
    media = [{"file": "media/x/001.jpg", "kind": "image"}]

    for hostile_id in ("../../../../etc/cron.d", "/etc/passwd", "..\\..\\windows"):
        with patch("models.urllib.request.urlopen") as mock_open:
            copied = models._copy_grading_media(run_id=7, job_id="job-1", netzwerk_id=hostile_id, media_list=media)
        assert copied == [], f"expected rejection for {hostile_id!r}"
        assert not mock_open.called, f"must not even attempt a request for {hostile_id!r}"

    # Nothing escaped the upload tree.
    for root, _dirs, files in os.walk(str(tmp_path)):
        assert "cron.d" not in root and "passwd" not in files and "windows" not in root


def test_copy_grading_media_skips_entry_missing_file_key(tmp_path, db):
    """A malformed media entry (no 'file' key) must be skipped, not crash with KeyError."""
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    config.UPLOAD_FOLDER = str(tmp_path)
    media = [{"kind": "image"}, {"file": "media/mueller.anna/001.jpg", "kind": "image"}]

    with patch("models.urllib.request.urlopen", return_value=_FakeResponse(b"ok")):
        copied = models._copy_grading_media(run_id=7, job_id="job-1", netzwerk_id="mueller.anna", media_list=media)

    assert len(copied) == 1
    assert copied[0]["file"] == "7/mueller.anna/001.jpg"
