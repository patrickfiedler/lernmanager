"""Tests for /internal/grading/lernpfad (2026-08-19) -- the machine-to-machine
lookup the grading service's service/worker.py:resolve_missing_lernpfad()
calls when a job's manifest is missing `lernpfad` for one or more students
(every scan-folders-batch.ps1 job today, since it has no local Seilbahn/track
data source at all). Mirrors the auth tests in test_grading_callback.py for
the sibling /internal/grading/results route.
"""
import json

import config
import models


def test_route_rejects_missing_secret(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post('/internal/grading/lernpfad', json={"logins": ["mueller.anna"]})
    assert resp.status_code == 401


def test_route_rejects_wrong_secret(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post(
        '/internal/grading/lernpfad', json={"logins": ["mueller.anna"]},
        headers={"X-Grading-Callback-Secret": "wrong"},
    )
    assert resp.status_code == 401


def test_route_rejects_non_list_logins(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post(
        '/internal/grading/lernpfad', json={"logins": "mueller.anna"},
        headers={"X-Grading-Callback-Secret": "s3cr3t"},
    )
    assert resp.status_code == 400


def test_route_returns_lernpfad_for_matched_logins(app, client, db):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    models.create_student("Bytyci", "Leandro", "u-lp-1", "pw",
                           lernpfad="seilbahn", netzwerk_id="bytyci.leand2")
    models.create_student("Bechler", "Romy", "u-lp-2", "pw",
                           lernpfad="bergweg", netzwerk_id="bechler.romy")

    resp = client.post(
        '/internal/grading/lernpfad',
        data=json.dumps({"logins": ["bytyci.leand2", "bechler.romy", "no.such.login"]}),
        content_type='application/json',
        headers={"X-Grading-Callback-Secret": "s3cr3t"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["lernpfad"] == {"bytyci.leand2": "seilbahn", "bechler.romy": "bergweg"}
    assert "no.such.login" not in body["lernpfad"]


def test_route_empty_logins_returns_empty_map(app, client):
    config.GRADING_SERVICE_CALLBACK_SECRET = "s3cr3t"
    resp = client.post(
        '/internal/grading/lernpfad', json={"logins": []},
        headers={"X-Grading-Callback-Secret": "s3cr3t"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["lernpfad"] == {}
