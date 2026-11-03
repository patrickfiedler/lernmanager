"""Tests for models._copy_grading_document -- the best-graded document and its
WebP preview pages, copied from the grading service at import time (decision
2026-11-03). urllib.request.urlopen is mocked; no real network.
"""
import io
import json
import os
from unittest.mock import patch

import config
import models


class _FakeResponse(io.BytesIO):
    def __exit__(self, *a):
        return False


DOC = {'file': 'abgabe.pptx', 'size': 1234, 'slimmed': True, 'skipped': None,
       'pages': ['page-001.webp', 'page-002.webp'], 'pages_total': 2, 'preview_error': None}


def _setup(tmp_path):
    config.GRADING_SERVICE_URL = "http://10.8.0.3:8420"
    config.GRADING_SERVICE_TOKEN = "test-token"
    config.UPLOAD_FOLDER = str(tmp_path)


def test_copies_download_and_pages_to_local_relpaths(tmp_path, db):
    _setup(tmp_path)
    urls = []

    def fake(req, timeout=None):
        urls.append(req.full_url)
        assert req.get_header("Authorization") == "Bearer test-token"
        return _FakeResponse(req.full_url.encode())

    with patch("models.urllib.request.urlopen", side_effect=fake):
        doc = models._copy_grading_document(7, "job-1", "mueller.anna", DOC)

    assert doc['file'] == "7/mueller.anna/dokument/abgabe.pptx"
    assert doc['pages'] == ["7/mueller.anna/dokument/page-001.webp",
                            "7/mueller.anna/dokument/page-002.webp"]
    assert doc['slimmed'] is True and doc['pages_total'] == 2
    assert urls == [
        "http://10.8.0.3:8420/jobs/job-1/document/mueller.anna",
        "http://10.8.0.3:8420/jobs/job-1/document/mueller.anna/pages/page-001.webp",
        "http://10.8.0.3:8420/jobs/job-1/document/mueller.anna/pages/page-002.webp",
    ]
    assert os.path.isfile(tmp_path / "grading" / "7" / "mueller.anna" / "dokument" / "abgabe.pptx")


def test_failed_download_is_named_not_dropped(tmp_path, db):
    _setup(tmp_path)

    def fake(req, timeout=None):
        if req.full_url.endswith("mueller.anna"):
            raise OSError("down")
        return _FakeResponse(b"webp")

    with patch("models.urllib.request.urlopen", side_effect=fake):
        doc = models._copy_grading_document(7, "job-1", "mueller.anna", DOC)
    assert doc['file'] is None and doc['skipped'] == 'copy_failed'
    assert len(doc['pages']) == 2


def test_service_reasons_pass_through_without_fetching(tmp_path, db):
    _setup(tmp_path)
    too_large = {'file': None, 'size': 30_000_000, 'skipped': 'too_large',
                 'pages': [], 'pages_total': 0, 'preview_error': 'Keine Vorschau für .sb3'}
    with patch("models.urllib.request.urlopen") as mock_open:
        doc = models._copy_grading_document(7, "job-1", "mueller.anna", too_large)
    mock_open.assert_not_called()
    assert doc['skipped'] == 'too_large' and doc['preview_error'] == 'Keine Vorschau für .sb3'


def test_hostile_names_never_reach_the_path(tmp_path, db):
    _setup(tmp_path)
    evil = dict(DOC, file='../../../app.py', pages=['../x.webp', 'page-001.webp.exe'])
    with patch("models.urllib.request.urlopen", side_effect=lambda r, timeout=None: _FakeResponse(b"x")):
        doc = models._copy_grading_document(7, "job-1", "mueller.anna", evil)
        assert models._copy_grading_document(7, "job-1", "../etc", DOC) is None
    assert doc['file'] == "7/mueller.anna/dokument/app.py"  # basename only
    assert doc['pages'] == []


def test_no_document_or_no_service_is_none(tmp_path, db):
    _setup(tmp_path)
    assert models._copy_grading_document(7, "job-1", "mueller.anna", None) is None
    config.GRADING_SERVICE_URL = ""
    assert models._copy_grading_document(7, "job-1", "mueller.anna", DOC) is None


def test_document_survives_the_round_trip_through_the_db(tmp_path, db):
    _setup(tmp_path)
    task_id = models.create_task("thema-doc", "d", "l", "MBI", "6", "pflicht")
    run_id = models.create_grading_run("job-doc", None, task_id, "r", "local", None, 1)
    stored = dict(DOC, file="1/x/dokument/abgabe.pptx")
    rid = models.create_grading_result(run_id, task_id, None, "x", [], document=stored)
    assert models.get_grading_result(rid)['document'] == stored
    rid2 = models.create_grading_result(run_id, task_id, None, "y", [])
    assert models.get_grading_result(rid2)['document'] is None


def test_grading_view_is_kept_per_account(app, as_admin):
    app.config["WTF_CSRF_ENABLED"] = False
    with as_admin.session_transaction() as sess:
        admin_id = sess["admin_id"]
    assert models.get_admin(admin_id)['grading_view'] == 'ki'
    assert as_admin.post('/admin/grading/ansicht', data={'view': 'beides'}).status_code == 200
    assert models.get_admin(admin_id)['grading_view'] == 'beides'
    assert as_admin.post('/admin/grading/ansicht', data={'view': '<script>'}).status_code == 400
    assert models.get_admin(admin_id)['grading_view'] == 'beides'


def _review_page(as_admin, document, purged=False):
    import uuid
    task_id = models.create_task("thema-" + uuid.uuid4().hex, "d", "l", "MBI", "6", "pflicht")
    run_id = models.create_grading_run(uuid.uuid4().hex, None, task_id, "r", "local", None, 1)
    rid = models.create_grading_result(run_id, task_id, None, "x", [{"name": "K", "score": 1, "max_score": 1}],
                                       document_file="abgabe.pptx", document=document)
    if purged:
        models.mark_grading_run_media_purged(run_id)
    return as_admin.get(f'/admin/grading-result/{rid}/review').get_data(as_text=True)


def test_review_page_offers_download_and_pages(as_admin):
    html = _review_page(as_admin, dict(DOC, file="1/x/dokument/abgabe.pptx",
                                       pages=["1/x/dokument/page-001.webp"], pages_total=3))
    assert 'data-view="ki"' in html
    assert '/grading-medien/1/x/dokument/abgabe.pptx' in html and 'Bilder verkleinert' in html
    assert '/grading-medien/1/x/dokument/page-001.webp' in html
    assert 'Weitere 2 Seite(n) nur in der Datei' in html


def test_review_page_names_why_there_is_no_file(as_admin):
    assert 'Keine Datei übernommen' in _review_page(as_admin, None)
    html = _review_page(as_admin, {'file': None, 'skipped': 'too_large', 'pages': [],
                                   'pages_total': 0, 'preview_error': 'Keine Vorschau für .sb3'})
    assert 'über 20 MB' in html and 'Keine Vorschau für .sb3' in html


def test_backfill_fills_only_results_without_document(tmp_path, db):
    _setup(tmp_path)
    import uuid
    task_id = models.create_task("thema-" + uuid.uuid4().hex, "d", "l", "MBI", "6", "pflicht")
    run_id = models.create_grading_run("job-alt", None, task_id, "r", "local", None, 2)
    leer = models.create_grading_result(run_id, task_id, None, "mueller.anna", [])
    schon = models.create_grading_result(run_id, task_id, None, "schulz.ben", [],
                                         document={'file': 'x', 'pages': []})
    results = {'students': [{'student_id': 'mueller.anna', 'document': DOC},
                            {'student_id': 'schulz.ben', 'document': DOC}]}
    seen = []

    def fake(req, timeout=None):
        seen.append((req.get_method(), req.full_url))
        if req.full_url.endswith('/documents'):
            return _FakeResponse(b'{"prepared": 2}')
        if req.full_url.endswith('/results'):
            return _FakeResponse(json.dumps(results).encode())
        return _FakeResponse(b'bytes')

    with patch("models.urllib.request.urlopen", side_effect=fake):
        assert models.backfill_grading_documents(run_id) == (1, None)
    assert seen[0] == ('POST', 'http://10.8.0.3:8420/jobs/job-alt/documents')
    assert models.get_grading_result(leer)['document']['file'].endswith('/dokument/abgabe.pptx')
    assert models.get_grading_result(schon)['document'] == {'file': 'x', 'pages': []}

    with patch("models.urllib.request.urlopen", side_effect=fake):
        assert models.backfill_grading_documents(run_id, again=True) == (2, None)
    assert models.get_grading_result(schon)['document']['file'].endswith('/dokument/abgabe.pptx')


def test_backfill_refuses_purged_run(tmp_path, db):
    _setup(tmp_path)
    task_id = models.create_task("thema-purged", "d", "l", "MBI", "6", "pflicht")
    run_id = models.create_grading_run("job-weg", None, task_id, "r", "local", None, 1)
    models.mark_grading_run_media_purged(run_id)
    with patch("models.urllib.request.urlopen") as mock_open:
        updated, error = models.backfill_grading_documents(run_id)
    mock_open.assert_not_called()
    assert updated == 0 and 'gelöscht' in error
