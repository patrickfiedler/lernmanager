"""Grading runs can be told apart: how the batch was collected (the
scan-folders log header in the zip) and a teacher-set name."""
import json
import re

import models

SCAN_LOG = (
    "﻿# Scan Log - 2026-09-11\n"
    "\n"
    "**Date**: 2026-09-11 13:45:23\n"
    "**Pattern(s)**: startklar\n"
    "**Class**: 7\n"
    "**Search Type**: file\n"
    "**File Selection**: newest\n"
    "\n"
    "## Results\n"
    "\n"
    "| Name | Course | Match | Files Copied |\n"
    "|------|--------|-------|--------------|\n"
    "| **Muster, Max** | 7a | startklar | 1 |\n"
)


def _task(keyword="unit-startklar"):
    task_id = models.create_task("Startklar", "desc", "lz", "MBI", "7", "pflicht")
    models.create_subtask(task_id, "Aufgabe 1", reihenfolge=1,
                          graded_artifact_json=json.dumps({"keyword": keyword}))
    return task_id


def test_parse_scan_log_reads_header():
    assert models.parse_scan_log(SCAN_LOG) == {
        "Date": "2026-09-11 13:45:23",
        "Pattern(s)": "startklar",
        "Class": "7",
        "Search Type": "file",
        "File Selection": "newest",
    }


def test_parse_scan_log_ignores_everything_after_the_header():
    # A bold student name in the results table must never become a setting.
    parsed = models.parse_scan_log(SCAN_LOG + "**Late**: nope\n")
    assert "Late" not in parsed
    assert not any("Muster" in k for k in parsed)


def test_parse_scan_log_not_a_log():
    assert models.parse_scan_log(None) == {}
    assert models.parse_scan_log("") == {}
    assert models.parse_scan_log("just some text\n**A**: b") == {}


def test_display_name_prefers_name_then_collection_then_task(db):
    task_id = _task()
    run_id = models.create_grading_run("j1", None, task_id, "unit-startklar", "ollama", None,
                                       collection=models.parse_scan_log(SCAN_LOG))
    assert models.get_grading_run(run_id)["display_name"] == "7 · startklar · 2026-09-11"

    models.rename_grading_run(run_id, "  7b Startklar, 2. Abgabe ")
    assert models.get_grading_run(run_id)["display_name"] == "7b Startklar, 2. Abgabe"

    models.rename_grading_run(run_id, "   ")  # blank = back to the default
    assert models.get_grading_run(run_id)["name"] is None

    bare = models.create_grading_run("j2", None, task_id, "unit-startklar", "ollama", None)
    assert models.get_grading_run(bare)["display_name"].startswith("Startklar · ")


def test_upload_complete_stores_collection(app, client, as_admin):
    task_id = _task()
    page = as_admin.get('/admin').get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    resp = as_admin.post(
        '/admin/grading/upload/complete',
        json={"job_id": "job-log", "task_id": task_id, "rubric": "unit-startklar",
              "provider": "ollama", "students": 3, "scan_log": SCAN_LOG},
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 201
    run = models.get_grading_run_by_job_id("job-log")
    assert json.loads(run["collection_json"])["Pattern(s)"] == "startklar"

    listing = as_admin.get('/admin/grading/runs').get_data(as_text=True)
    assert "7 · startklar · 2026-09-11" in listing


def test_rename_route(app, client, as_admin):
    run_id = models.create_grading_run("j3", None, _task(), "unit-startklar", "ollama", None)
    page = as_admin.get(f'/admin/grading-run/{run_id}').get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    resp = as_admin.post(f'/admin/grading-run/{run_id}/name',
                         data={"name": "Fertig: 7b", "csrf_token": token})
    assert resp.status_code == 302
    assert models.get_grading_run(run_id)["name"] == "Fertig: 7b"


def test_callback_auto_created_run_keeps_scan_log(db):
    _task()
    run_id = models.import_grading_callback(
        job_id="scan-job", provider="ovh", model="m", graded_at=None,
        students=[], rubric="unit-startklar", scan_log=SCAN_LOG)
    assert models.get_grading_run(run_id)["collection"]["Class"] == "7"
