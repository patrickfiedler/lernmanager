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
}

# URL parameters that never point at one class or student: any value will do.
UNSCOPED_PARAMS = {'task_id', 'material_id', 'datum', 'question_index',
                   'checkpoint_id', 'filename', 'relpath'}


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
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_id"] = teacher['id']
    return client, {'klasse_id': other, 'student_id': student}


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
