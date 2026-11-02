"""Audit log, undo, full run delete and the review-every-student state."""
import os
import re
from unittest.mock import patch

import config
import models

CRIT = [{"name": "X", "llm_score": 1, "max_score": 1}]


def _run(job_id="job-audit", names=("Anna", "Bert")):
    task_id = models.create_task("thema-audit-" + job_id, "d", "l", "MBI", "6", "pflicht")
    run_id = models.create_grading_run(job_id, None, task_id, "r", "local", None, len(names),
                                       graded_at="2026-11-02T10:00:00")
    ids = {}
    for n in names:
        sid = models.create_student(n, "X", f"u{job_id}{n}", "pw", netzwerk_id=f"{job_id}.{n}".lower())
        ids[n] = models.create_grading_result(run_id, task_id, sid, f"{job_id}.{n}".lower(), CRIT)
    return run_id, task_id, ids


def _admin():
    with models.db_session() as conn:
        row = conn.execute("SELECT id FROM admin LIMIT 1").fetchone()
        if row:
            return row['id']
        return conn.execute("INSERT INTO admin (username, password_hash) VALUES ('t', 'x')").lastrowid


def _status(result_id):
    return models.get_grading_result(result_id)['status']


def _save(result_id, score=1, admin=None):
    criteria = [dict(CRIT[0], teacher_score=score)]
    with models.grading_audit(admin or _admin(), 'review', [result_id]):
        models.save_grading_result_review(result_id, criteria)


def test_every_student_stays_open_until_reviewed(db):
    run_id, _, ids = _run()
    assert models.grading_result_is_open(models.get_grading_result(ids["Anna"]))
    _save(ids["Anna"])
    assert not models.grading_result_is_open(models.get_grading_result(ids["Anna"]))


def test_unconfirmed_criterion_keeps_a_reviewed_result_open(db):
    run_id, task_id, _ = _run()
    sid = models.create_student("C", "C", "uc", "pw", netzwerk_id="c.c")
    crit = [{"name": "B", "llm_score": 1, "max_score": 1, "review_required": True}]
    rid = models.create_grading_result(run_id, task_id, sid, "c.c", crit)
    models.save_grading_result_review(rid, [dict(crit[0], teacher_score=1)])
    assert models.grading_result_is_open(models.get_grading_result(rid))


def test_next_skips_students_already_checked(db):
    run_id, _, ids = _run(names=("Anna", "Bert", "Carl"))
    _save(ids["Bert"])
    assert models.get_next_in_review_queue(run_id, ids["Anna"])["id"] == ids["Carl"]


def test_unchanged_result_leaves_no_log_row(db):
    run_id, _, ids = _run()
    with models.grading_audit(_admin(), 'release_bulk', list(ids.values())):
        models.release_grading_result(ids["Anna"], _admin())
    rows = models.list_grading_audit(run_id)
    assert [r['grading_result_id'] for r in rows] == [ids["Anna"]]
    assert rows[0]['actor']


def test_undo_restores_release_and_score(db):
    run_id, _, ids = _run()
    _save(ids["Anna"], score=0)
    with models.grading_audit(_admin(), 'release', [ids["Anna"]]):
        models.release_grading_result(ids["Anna"], _admin())
    release = models.list_grading_audit(run_id)[0]
    assert models.undo_grading_decisions([release['id']], _admin())[:2] == (1, 0)
    assert _status(ids["Anna"]) == 'under_review'
    assert models.get_grading_result(ids["Anna"])['released_at'] is None

    review = next(r for r in models.list_grading_audit(run_id) if r['action'] == 'review')
    models.undo_grading_decisions([review['id']], _admin())
    result = models.get_grading_result(ids["Anna"])
    assert result['status'] == 'imported' and result['teacher_total_score'] is None


def test_undo_refuses_when_a_later_decision_exists(db):
    run_id, _, ids = _run()
    _save(ids["Anna"], score=0)
    review = models.list_grading_audit(run_id)[0]
    with models.grading_audit(_admin(), 'release', [ids["Anna"]]):
        models.release_grading_result(ids["Anna"], _admin())
    assert models.undo_grading_decisions([review['id']], _admin())[:2] == (0, 1)
    assert _status(ids["Anna"]) == 'active'


def test_batch_undo_and_no_double_undo(db):
    run_id, _, ids = _run()
    with models.grading_audit(_admin(), 'release_bulk', list(ids.values())):
        for rid in ids.values():
            models.release_grading_result(rid, _admin())
    rows = models.list_grading_audit(run_id)
    assert len({r['batch_id'] for r in rows}) == 1
    all_ids = [r['id'] for r in rows]
    assert models.undo_grading_decisions(all_ids, _admin())[0] == 2
    assert models.undo_grading_decisions(all_ids, _admin())[0] == 0


def test_supersede_undo_gives_active_back(db):
    run1, task_id, ids = _run(job_id="j1", names=("Anna",))
    old = ids["Anna"]
    models.release_grading_result(old, _admin())
    sid = models.get_grading_result(old)['student_id']
    run2 = models.create_grading_run("j2", None, task_id, "r", "local", None, 1)
    new = models.create_grading_result(run2, task_id, sid, "x", CRIT)
    with models.grading_audit(_admin(), 'supersede', [old, new]):
        models.supersede_grading_result(old, new)
        models.release_grading_result(new, _admin())
    rows = models.list_grading_audit(run1) + models.list_grading_audit(run2)
    assert models.undo_grading_decisions([r['id'] for r in rows], _admin())[:2] == (2, 0)
    assert _status(old) == 'active' and _status(new) == 'imported'


def test_delete_run_removes_everything_keeps_log_restores_replaced(db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'UPLOAD_FOLDER', str(tmp_path))
    run1, task_id, ids = _run(job_id="d1", names=("Anna",))
    old = ids["Anna"]
    models.release_grading_result(old, _admin())
    run2 = models.create_grading_run("d2", None, task_id, "r", "local", None, 1)
    new = models.create_grading_result(run2, task_id, models.get_grading_result(old)['student_id'], "x", CRIT)
    models.supersede_grading_result(old, new)
    models.release_grading_result(new, _admin())
    folder = os.path.join(models._grading_upload_dir(), str(run2), 'reports')
    os.makedirs(folder)

    monkeypatch.setattr(config, 'GRADING_SERVICE_URL', '')
    assert models.delete_grading_run(run2, _admin()) is True

    assert models.get_grading_run(run2) is None
    assert models.get_grading_result(new) is None
    assert not os.path.exists(os.path.dirname(folder))
    assert _status(old) == 'active'
    assert models.list_grading_audit(run2)[0]['action'] == 'delete_run'


def test_delete_reports_unreachable_service(db, monkeypatch):
    run_id, _, _ = _run(job_id="d3")
    monkeypatch.setattr(config, 'GRADING_SERVICE_URL', 'http://service')
    with patch('urllib.request.urlopen', side_effect=OSError('down')):
        assert models.delete_grading_run(run_id, _admin()) is False


def test_student_delete_removes_their_log_rows(db):
    run_id, _, ids = _run()
    sid = models.get_grading_result(ids["Anna"])['student_id']
    _save(ids["Anna"])
    models.delete_student(sid)
    assert models.list_grading_audit(run_id) == []


def test_media_kept_for_undo_until_keep_days_passed(db, monkeypatch):
    run_id, _, ids = _run(names=("Anna",))
    with models.grading_audit(_admin(), 'discard', [ids["Anna"]]):
        models.discard_grading_result(ids["Anna"])
    monkeypatch.setattr(config, 'GRADING_MEDIA_KEEP_DAYS', 14)
    models.purge_settled_grading_runs()
    assert models.get_grading_run(run_id)['media_purged_at'] is None
    monkeypatch.setattr(config, 'GRADING_MEDIA_KEEP_DAYS', 0)
    models.purge_settled_grading_runs()
    assert models.get_grading_run(run_id)['media_purged_at'] is not None


def test_pages_and_routes(app, client, as_admin, monkeypatch):
    run_id, _, ids = _run()
    html = client.get(f'/admin/grading-run/{run_id}').get_data(as_text=True)
    assert 'noch zu prüfen' in html and 'Prüfung starten' in html
    assert html.index('Prüfung starten') < html.index('Technik')
    assert html.index('👥 Schüler') < html.index('Import-Übersicht')
    assert 'prüfen</a>' in client.get('/admin').get_data(as_text=True)

    client.post(f"/admin/grading-result/{ids['Anna']}/review", data={'action': 'save'})
    assert 'Geprüft' in client.get(f'/admin/grading/verlauf?run={run_id}').get_data(as_text=True)

    audit_id = models.list_grading_audit(run_id)[0]['id']
    monkeypatch.setattr(models, 'regenerate_grading_reports', lambda r: (True, 'ok'))
    client.post('/admin/grading/verlauf/rueckgaengig', data={'audit_id': audit_id})
    assert _status(ids['Anna']) == 'imported'

    monkeypatch.setattr(config, 'GRADING_SERVICE_URL', '')
    client.post(f'/admin/grading-run/{run_id}/loeschen')
    assert models.get_grading_run(run_id) is None
    assert 'Lauf gelöscht' in client.get('/admin/grading/verlauf').get_data(as_text=True)
