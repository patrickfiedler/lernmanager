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
