"""Teacher role: every staff page is classified, and a teacher reaches nothing foreign.

See permissions.py. Three layers:
1. Every /admin route carries @admin_required or @staff_required, and every other
   route that looks at session['admin_id'] by hand is listed in MANUAL_CHECK (and
   so has been read by someone).
2. A teacher gets 404 from every admin-only route.
3. A teacher gets 404 from every staff route when the ids in the URL belong to a
   class she does not teach. A staff route with a URL parameter this file cannot
   fill with a foreign object fails the test: add the object to `foreign` first.
"""
import inspect
import json
import re

import pytest

import models
from app import app as flask_app

# Routes outside the decorators that read session['admin_id'] themselves, each
# checked by hand for what a teacher may do there.
MANUAL_CHECK = {
    'index',                      # redirect only
    'login',
    'download_material',          # topic material: every logged-in user
    'download_student_artifact',  # permissions.can_see_student
    'vorschau_beenden',           # only drops the preview keys from the session
}

# URL parameters that never point at one class or student: any value will do.
UNSCOPED_PARAMS = {'task_id', 'material_id', 'datum', 'question_index', 'checkpoint_id'}


def _grading_run(job_id, task, *students):
    """A run with one reviewable result per (student, netzwerk_id)."""
    run = models.create_grading_run(job_id, None, task, "r", "local", None, len(students))
    results = [models.create_grading_result(
        run, task, student, login, [{"name": "K", "score": 1, "max_score": 1}],
        llm_total_score=1, llm_max_score=1, document_file="a.docx",
        media=[{"file": f"{run}/{login}/001.jpg", "source": "a.docx"}])
        for student, login in students]
    return run, results


@pytest.fixture
def teacher(app):
    """Teacher with one class of her own; a second class + student she does not teach."""
    app.config["WTF_CSRF_ENABLED"] = False
    models.create_admin("lehrerin", "testpass", role="teacher")
    teacher = models.verify_admin("lehrerin", "testpass")
    own = models.create_klasse("Eigene")
    models.add_teacher_to_klasse(teacher['id'], own)
    other = models.create_klasse("Fremde")
    student = models.create_student("Fremd", "Fritz", "fremdfritz", "x")
    models.add_student_to_klasse(student, other)
    unterricht = models.create_or_get_unterricht(other, '2026-10-26')
    # Checkpoint work of the foreign student, on a topic of the foreign class.
    task = models.create_task("Fremdes Thema", "", "", "Chemie", "11", "")
    models.assign_task_to_student(student, other, task)
    sub = models.create_subtask(task, "### CP", reihenfolge=0,
                                quiz_json=json.dumps({"questions": []}), checkpoint_type="quiz")
    # Answer before attempt: create_checkpoint_attempt links the session's answers.
    answer = models.create_checkpoint_answer(student, sub, "f1", 0, 1, "x", False, "", "llm")['id']
    attempt = models.create_checkpoint_attempt(student, sub, task, "quiz", "kern", score=2,
                                               session_uid="f1")
    flag = models.create_checkpoint_flag(sub, 0, 'student', student_id=student, session_uid="f1",
                                         checkpoint_attempt_id=attempt)
    run, (result,) = _grading_run("fremd", task, (student, "fremd.fritz"))
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = teacher['id']
    return client, {'klasse_id': other, 'student_id': student, 'unterricht_id': unterricht,
                    'attempt_id': attempt, 'answer_id': answer, 'flag_id': flag,
                    'checkpoint_id': sub, 'run_id': run, 'result_id': result,
                    'relpath': f'{run}/fremd.fritz/001.jpg', 'filename': 'grades.csv'}


@pytest.fixture
def own(app, teacher):
    """The teacher's own objects, for pages she is supposed to open."""
    client, _ = teacher
    klasse = models.get_klasse_ids_for_teacher(
        models.verify_admin("lehrerin", "testpass")['id']).pop()
    student = models.create_student("Eigen", "Emma", "eigenemma", "x")
    models.add_student_to_klasse(student, klasse)
    task = models.create_task("Thema A", "", "", "MBI", "5", "pflicht")
    models.assign_task_to_student(student, klasse, task)
    sub = models.create_subtask(task, "### CP eigen", reihenfolge=0,
                                quiz_json=json.dumps({"questions": [{"text": "F?", "options": ["a"], "correct": [0]}]}),
                                checkpoint_type="quiz")
    models.create_checkpoint_answer(student, sub, "e1", 0, 1, "a", True, "", "llm")
    models.create_checkpoint_attempt(student, sub, task, "quiz", "kern", score=2, session_uid="e1")
    unterricht = models.create_or_get_unterricht(klasse, '2026-10-26')
    run, (result,) = _grading_run("eigen", task, (student, "eigen.emma"))
    return client, {'klasse_id': klasse, 'student_id': student, 'task_id': task,
                    'unterricht_id': unterricht, 'datum': '2026-10-26',
                    'run_id': run, 'result_id': result}


def _admin_rules():
    for rule in flask_app.url_map.iter_rules():
        view = flask_app.view_functions[rule.endpoint]
        if hasattr(view, 'access'):
            yield rule, view.access


def _url(rule, values):
    url = rule.rule
    for arg in rule.arguments:
        value = values.get(arg, 1 if arg.endswith('_id') or arg.endswith('_index') else 'x')
        url = re.sub(r'<(?:[^:<>]+:)?%s>' % arg, str(value), url)
    return url


def _methods(rule):
    return sorted(rule.methods & {'GET', 'POST'})


def test_every_admin_route_is_classified():
    unclassified = [r.rule for r in flask_app.url_map.iter_rules()
                    if r.rule.startswith('/admin')
                    and not hasattr(flask_app.view_functions[r.endpoint], 'access')]
    assert unclassified == []


def test_hand_checked_routes_are_listed():
    unlisted = []
    for endpoint, view in flask_app.view_functions.items():
        if hasattr(view, 'access') or endpoint in MANUAL_CHECK:
            continue
        try:
            source = inspect.getsource(view)
        except (OSError, TypeError):
            continue
        if 'admin_id' in source:
            unlisted.append(endpoint)
    assert unlisted == [], "read these for teacher access, then add to MANUAL_CHECK"


def test_teacher_gets_404_on_admin_only_routes(teacher):
    client, foreign = teacher
    reached = []
    for rule, access in _admin_rules():
        if access != 'admin':
            continue
        for method in _methods(rule):
            resp = client.open(_url(rule, foreign), method=method)
            if resp.status_code != 404:
                reached.append(f"{method} {rule.rule} -> {resp.status_code}")
    assert reached == []


def test_teacher_gets_404_on_foreign_ids(teacher):
    client, foreign = teacher
    reached, unfillable = [], []
    for rule, access in _admin_rules():
        if access != 'staff':
            continue
        scoped = [a for a in rule.arguments if a not in UNSCOPED_PARAMS]
        missing = [a for a in scoped if a not in foreign]
        if missing:
            unfillable.append(f"{rule.rule}: {missing}")
            continue
        if not scoped:
            continue  # list pages: covered by their own content tests
        for method in _methods(rule):
            resp = client.open(_url(rule, foreign), method=method)
            if resp.status_code != 404:
                reached.append(f"{method} {rule.rule} -> {resp.status_code}")
    assert unfillable == [], "add a foreign object for these parameters"
    assert reached == []


def _links(html):
    return re.findall(r'(?:href|action)="(/[^"#?]*)', html)


def _endpoint(adapter, path):
    for method in ('GET', 'POST'):
        try:
            return adapter.match(path, method=method)[0]
        except Exception:
            pass
    return None


def test_teacher_pages_link_only_to_pages_she_may_open(own):
    """Render every staff GET page with the teacher's own ids: no link or form on it
    may lead to an admin-only page (hiding is comfort, but a dead button confuses)."""
    client, ids = own
    adapter = flask_app.url_map.bind('localhost')
    bad, broken = [], []
    for rule, access in _admin_rules():
        if access != 'staff' or 'GET' not in rule.methods:
            continue
        if any(a not in ids and a not in UNSCOPED_PARAMS for a in rule.arguments):
            continue
        url = _url(rule, ids)
        resp = client.get(url)
        if resp.status_code != 200 or resp.mimetype != 'text/html':
            if resp.status_code >= 400:
                broken.append(f"{url} -> {resp.status_code}")
            continue
        for link in _links(resp.get_data(as_text=True)):
            endpoint = _endpoint(adapter, link)
            if endpoint and getattr(flask_app.view_functions[endpoint], 'access', None) == 'admin':
                bad.append(f"{url} -> {link}")
    assert not broken, "\n".join(broken)
    assert not bad, "\n".join(sorted(set(bad)))


def test_teacher_sees_only_own_classes(own, teacher):
    client, ids = own
    html = client.get('/admin/klassen').get_data(as_text=True)
    assert 'Eigene' in html and 'Fremde' not in html


def test_batch_move_ignores_students_from_other_classes(app, own, teacher):
    client, ids = own
    _, foreign = teacher
    second = models.create_klasse("Eigene 2")
    models.add_teacher_to_klasse(models.verify_admin("lehrerin", "testpass")['id'], second)
    client.post(f"/admin/klasse/{ids['klasse_id']}/schueler-verschieben-batch",
                data={'to_klasse': second, 'student_ids': [foreign['student_id']]})
    assert models.get_klasse_ids_for_student(foreign['student_id']) == {foreign['klasse_id']}


def test_teacher_removes_student_from_class_account_stays(own):
    client, ids = own
    client.post(f"/admin/schueler/{ids['student_id']}/klasse/{ids['klasse_id']}/entfernen")
    assert models.get_klasse_ids_for_student(ids['student_id']) == set()
    assert models.get_student(ids['student_id']) is not None


def test_unfinished_checkpoints_list_only_own_classes(own, teacher):
    client, ids = own
    _, foreign = teacher
    with models.db_session() as conn:   # the fixtures' finished attempts would hide the work
        conn.execute("UPDATE checkpoint_attempt SET superseded_at = '2000-01-01 00:00:00'")
        own_checkpoint = conn.execute("SELECT id FROM subtask WHERE task_id = ?",
                                      (ids['task_id'],)).fetchone()['id']
    for student_id, checkpoint_id in ((ids['student_id'], own_checkpoint),
                                      (foreign['student_id'], foreign['checkpoint_id'])):
        models.create_checkpoint_answer(student_id, checkpoint_id, f"halb-{student_id}", 0,
                                        1, "halb", False, "", "llm")
    html = client.get('/admin/checkpoint-pruefung?ansicht=angefangen').get_data(as_text=True)
    assert 'Emma' in html
    assert 'Fritz' not in html


def test_deactivated_teacher_is_logged_out(own):
    client, _ = own
    with models.db_session() as conn:
        conn.execute("UPDATE admin SET active = 0 WHERE username = 'lehrerin'")
    resp = client.get('/admin/klassen')
    assert resp.status_code == 302 and '/login' in resp.location


def test_checkpoint_review_lists_only_own_classes(own, teacher):
    """The review page and every bulk action read through _checkpoint_filters."""
    client, _ = own
    _, foreign = teacher
    html = client.get('/admin/checkpoint-pruefung').get_data(as_text=True)
    assert 'Emma' in html       # her own student's session is there
    assert 'Fritz' not in html  # the student; the topic name may show (library is shared)
    html = client.get('/admin/checkpoint-pruefung?ansicht=fragen').get_data(as_text=True)
    assert 'Diese Frage bemängeln' not in html
    client.post('/admin/checkpoint-pruefung/zuruecksetzen',
                data={'checkpoint_id': foreign['checkpoint_id']})
    assert all(a['superseded_at'] is None for a in models.get_checkpoint_reviews())
    # Same pages/requests as admin: the teacher asserts above are not passing by accident.
    admin = flask_app.test_client()
    with admin.session_transaction() as sess:
        sess["admin_id"] = 1
    html = admin.get('/admin/checkpoint-pruefung?ansicht=fragen').get_data(as_text=True)
    assert 'Diese Frage bemängeln' in html
    admin.post('/admin/checkpoint-pruefung/zuruecksetzen',
               data={'checkpoint_id': foreign['checkpoint_id']})
    assert models.get_checkpoint_reviews(checkpoint_id=foreign['checkpoint_id']) == []


@pytest.fixture
def mixed_run(own, teacher):
    """One run across her class and a foreign one, plus an unmatched login."""
    client, ids = own
    _, foreign = teacher
    second = models.create_student("Eigen", "Eva", "eigeneva", "x")
    models.add_student_to_klasse(second, ids['klasse_id'])
    models.assign_task_to_student(second, ids['klasse_id'], ids['task_id'])
    run, (emma, eva, fritz, unmatched) = _grading_run(
        "gemischt", ids['task_id'], (ids['student_id'], "eigen.emma"), (second, "eigen.eva"),
        (foreign['student_id'], "fremd.fritz"), (None, "unbekannt"))
    return client, run, {'emma': emma, 'eva': eva, 'fritz': fritz, 'unmatched': unmatched}


def test_teacher_sees_only_her_students_in_a_shared_run(mixed_run):
    client, run, results = mixed_run
    html = client.get(f'/admin/grading-run/{run}').get_data(as_text=True)
    assert 'Emma' in html and 'Eva' in html
    assert 'Fritz' not in html and 'unbekannt' not in html
    assert 'anderer Klassen' in html
    assert client.get(f"/admin/grading-result/{results['fritz']}/review").status_code == 404
    assert client.get(f"/admin/grading-result/{results['unmatched']}/review").status_code == 404
    assert client.get(f'/admin/grading-run/{run}/bericht/grades.csv').status_code == 404
    assert client.post(f'/admin/grading-run/{run}/berichte-neu').status_code == 404
    listed = next(r for r in models.list_grading_runs() if r['id'] == run)
    assert listed['total_students'] == 4
    assert '<td>2</td>' in client.get('/admin/grading/runs').get_data(as_text=True)


def test_review_queue_stays_inside_her_classes(mixed_run):
    client, run, results = mixed_run
    resp = client.post(f"/admin/grading-result/{results['emma']}/review", data={'action': 'skip'})
    assert resp.location.endswith(f"/grading-result/{results['eva']}/review")
    resp = client.post(f"/admin/grading-result/{results['eva']}/review", data={'action': 'skip'})
    assert resp.location.endswith(f'/grading-run/{run}')
    assert '/ 2' in client.get(f"/admin/grading-result/{results['eva']}/review").get_data(as_text=True)


def test_teacher_gets_slips_with_only_her_students(mixed_run, monkeypatch):
    client, run, results = mixed_run
    sent = {}

    def fake(payload):
        sent.update(payload)
        return {'files': {'print_slips.html': '<html>zettel</html>'}}, None

    monkeypatch.setattr(models, '_request_grading_reports', fake)
    monkeypatch.setattr(models.config, 'GRADING_SERVICE_URL', 'http://service')
    resp = client.post(f'/admin/grading-run/{run}/eigene-datei/print_slips.html')
    assert resp.status_code == 200 and b'zettel' in resp.data
    assert {s['student_id'] for s in sent['students']} == {'eigen.emma', 'eigen.eva'}
    assert 'job_id' not in sent
    assert client.post(f'/admin/grading-run/{run}/eigene-datei/x.exe').status_code == 404


def test_admin_sees_which_teacher_sees_a_run(mixed_run, teacher):
    client, run, _ = mixed_run
    with client.session_transaction() as sess:
        teacher_id = sess['admin_id']
    with models.db_session() as conn:
        admin = conn.execute("SELECT id FROM admin WHERE role = 'admin' LIMIT 1").fetchone()
        username = conn.execute("SELECT username FROM admin WHERE id = ?", (teacher_id,)).fetchone()['username']
        admin_id = admin['id'] if admin else conn.execute(
            "INSERT INTO admin (username, password_hash) VALUES ('chef', 'x')").lastrowid
    with client.session_transaction() as sess:
        sess['admin_id'] = admin_id
    assert f'{username} (2/4)' in client.get('/admin/grading/runs').get_data(as_text=True)
    assert f'{username} (2 von 4 Schülern)' in client.get(f'/admin/grading-run/{run}').get_data(as_text=True)

    with models.db_session() as conn:
        conn.execute("UPDATE admin SET active = 0 WHERE id = ?", (teacher_id,))
    assert username not in client.get('/admin/grading/runs').get_data(as_text=True).split('Sichtbar für')[1]


def test_hand_set_class_decides_who_sees_a_result(mixed_run, teacher):
    client, run, results = mixed_run
    _, foreign = teacher
    models.set_grading_result_klasse(results['emma'], foreign['klasse_id'])
    html = client.get(f'/admin/grading-run/{run}').get_data(as_text=True)
    assert 'Eva' in html and 'Emma' not in html
    assert client.get(f"/admin/grading-result/{results['emma']}/review").status_code == 404

    models.set_grading_result_klasse(results['emma'], None)
    assert 'Emma' in client.get(f'/admin/grading-run/{run}').get_data(as_text=True)
    assert client.post(f"/admin/grading-result/{results['emma']}/klasse",
                       data={'klasse_id': foreign['klasse_id']}).status_code != 200
    assert models.get_grading_result(results['emma'])['klasse_id'] is None


def test_teacher_sees_no_reverse_lookup(mixed_run):
    client, run, _ = mixed_run
    assert 'Sichtbar für' not in client.get('/admin/grading/runs').get_data(as_text=True)
    assert 'Sichtbar für' not in client.get(f'/admin/grading-run/{run}').get_data(as_text=True)


def test_teacher_cannot_delete_a_run(mixed_run):
    client, run, _ = mixed_run
    assert client.post(f'/admin/grading-run/{run}/loeschen').status_code in (302, 403, 404)
    assert models.get_grading_run(run)


def test_audit_log_and_undo_stay_inside_her_classes(mixed_run, monkeypatch):
    monkeypatch.setattr(models, 'regenerate_grading_reports', lambda run_id: (True, 'ok'))
    client, run, results = mixed_run
    with models.grading_audit(None, 'discard', [results['fritz'], results['emma']]):
        models.discard_grading_result(results['fritz'])
        models.discard_grading_result(results['emma'])
    rows = {r['grading_result_id']: r for r in models.list_grading_audit(run)}

    html = client.get(f'/admin/grading/verlauf?run={run}').get_data(as_text=True)
    assert 'Emma' in html and 'Fritz' not in html
    resp = client.post('/admin/grading/verlauf/rueckgaengig',
                       data={'audit_id': rows[results['fritz']]['id']})
    assert resp.status_code == 404

    client.post('/admin/grading/verlauf/rueckgaengig',
                data={'audit_id': rows[results['emma']]['id'], 'scope': 'batch'})
    status = {r['id']: r['status'] for r in models.list_grading_results(run)}
    assert status[results['emma']] == 'imported'
    assert status[results['fritz']] == 'discarded'


def test_bulk_release_leaves_other_classes_alone(mixed_run, monkeypatch):
    monkeypatch.setattr(models, 'regenerate_grading_reports', lambda run_id: (True, 'ok'))
    client, run, results = mixed_run
    for name in ('emma', 'eva'):
        client.post(f"/admin/grading-result/{results[name]}/review", data={'action': 'save'})
    client.post(f'/admin/grading-run/{run}/release-bulk')
    status = {r['id']: r['status'] for r in models.list_grading_results(run)}
    assert status[results['emma']] == status[results['eva']] == 'active'
    assert status[results['fritz']] == 'imported'
    assert status[results['unmatched']] == 'imported'


def test_teacher_gets_media_of_her_students_only(mixed_run, tmp_path, monkeypatch):
    monkeypatch.setattr(models.config, 'UPLOAD_FOLDER', str(tmp_path))
    client, run, _ = mixed_run
    for login in ('eigen.emma', 'fremd.fritz'):
        folder = tmp_path / 'grading' / str(run) / login
        folder.mkdir(parents=True)
        (folder / '001.jpg').write_bytes(b'bild')
    assert client.get(f'/grading-medien/{run}/eigen.emma/001.jpg').status_code == 200
    assert client.get(f'/grading-medien/{run}/fremd.fritz/001.jpg').status_code == 404
    assert client.get(f'/grading-medien/{run}/eigen.emma/../fremd.fritz/001.jpg').status_code == 404


def test_teacher_owns_reports_when_the_whole_run_is_hers(own, tmp_path, monkeypatch):
    monkeypatch.setattr(models.config, 'UPLOAD_FOLDER', str(tmp_path))
    client, ids = own
    reports = tmp_path / 'grading' / str(ids['run_id']) / 'reports'
    reports.mkdir(parents=True)
    (reports / 'grades.csv').write_text('x')
    assert client.get(f"/admin/grading-run/{ids['run_id']}/bericht/grades.csv").status_code == 200


def test_artifact_before_assignment_counts_by_the_students_classes(own):
    """No student_task row for that topic: the result must not vanish from her view."""
    client, ids = own
    unassigned = models.create_task("Noch nicht zugewiesen", "", "", "MBI", "5", "pflicht")
    run, (result,) = _grading_run("frueh", unassigned, (ids['student_id'], "eigen.emma"))
    assert client.get(f'/admin/grading-result/{result}/review').status_code == 200


def test_admin_creates_teacher_who_then_sees_her_class(app, monkeypatch):
    """End to end through the real login form, not a session shortcut."""
    import app as app_module
    password = 'bacado42'  # the real one is only in the PDF
    monkeypatch.setattr(app_module, 'generate_password', lambda: password)
    app.config["WTF_CSRF_ENABLED"] = False
    klasse = models.create_klasse("Eigenklasse")
    models.create_klasse("Fremdklasse")
    admin = app.test_client()
    with admin.session_transaction() as sess:
        sess["admin_id"] = 1
    resp = admin.post('/admin/lehrkraefte/neu',
                      data={'nachname': 'Bauer', 'vorname': 'Anna', 'username': 'kollegin'})
    assert resp.mimetype == 'application/pdf'
    teacher_id = models.verify_admin('kollegin', password)['id']
    admin.post(f'/admin/lehrkraft/{teacher_id}/klassen', data={'klasse_ids': [klasse]})

    colleague = app.test_client()
    colleague.post('/login', data={'username': 'kollegin', 'password': password})
    html = colleague.get('/admin/klassen').get_data(as_text=True)
    assert 'Eigenklasse' in html and 'Fremdklasse' not in html
    assert colleague.get('/admin/lehrkraefte').status_code == 404

    admin.post(f'/admin/lehrkraft/{teacher_id}/aktiv')
    assert colleague.get('/admin/klassen').status_code == 302
    login = app.test_client().post('/login', data={'username': 'kollegin', 'password': password},
                                   follow_redirects=True)
    assert 'deaktiviert' in login.get_data(as_text=True)
