"""Who may see what: admin vs. teacher.

Patrick, 2026-10-26: colleagues get `teacher` accounts (admin.role). A teacher sees
only the classes linked to her in klasse_lehrer, the students in those classes, and
only the data those classes produce. Every rule lives here, so widening a teacher's
rights later (e.g. editing her own topics) is a change in this file, not in app.py.

Two decorators, every /admin route carries exactly one:
    @admin_required   admin only (also the default for anything not opened up)
    @staff_required   admin + teacher; the route must then scope its data with
                      require_klasse / require_student or visible_klasse_ids

Refusal is 404, not 403: a teacher must not learn that someone else's class exists.
The role is read from the DB on every request, not cached in the session, so
deactivating an account or changing its role takes effect at the next click.
"""
from functools import wraps

from flask import abort, flash, g, redirect, session, url_for

import models


def current_staff():
    """The logged-in admin/teacher row, or None. Loaded once per request."""
    if 'staff' not in g:
        admin_id = session.get('admin_id')
        g.staff = models.get_admin(admin_id) if admin_id else None
    return g.staff


def is_admin():
    staff = current_staff()
    return bool(staff) and staff['role'] == 'admin'


def visible_klasse_ids():
    """None = all classes (admin). Otherwise the set of class ids this teacher teaches."""
    if is_admin():
        return None
    staff = current_staff()
    return models.get_klasse_ids_for_teacher(staff['id']) if staff else set()


def visible_klassen():
    """models.get_all_klassen(), cut down to what this user may see."""
    ids = visible_klasse_ids()
    return [k for k in models.get_all_klassen() if ids is None or k['id'] in ids]


def can_see_klasse(klasse_id):
    ids = visible_klasse_ids()
    return ids is None or klasse_id in ids


def can_see_student(student_id):
    """A teacher sees a student who sits in at least one of her classes."""
    ids = visible_klasse_ids()
    return ids is None or bool(ids & models.get_klasse_ids_for_student(student_id))


def can_see_student_topic(student_id, task_id):
    """Work a student did on one topic: visible if the topic belongs to one of her
    classes. A student shared with another teacher's class stays partly hidden."""
    ids = visible_klasse_ids()
    return ids is None or bool(ids & models.get_klasse_ids_for_student_topic(student_id, task_id))


def require_checkpoint(kind, row_id):
    """kind: 'attempt' | 'flag' | 'answer' (models.get_checkpoint_owner). A teacher's
    own question flag (no student) is a verdict about the question: admin only."""
    if is_admin():
        return
    owner = models.get_checkpoint_owner(kind, row_id)
    if not owner or owner[0] is None or not can_see_student_topic(*owner):
        abort(404)


def require_klasse(klasse_id):
    if not can_see_klasse(klasse_id):
        abort(404)


def require_unterricht(unterricht_id):
    """A lesson belongs to one class; unknown lessons are 404 too."""
    klasse_id = models.get_unterricht_klasse_id(unterricht_id)
    if klasse_id is None or not can_see_klasse(klasse_id):
        abort(404)


def require_student(student_id):
    if not can_see_student(student_id):
        abort(404)


def can_preview_student(student_id):
    """Looking at the student pages as this student. They show every class the
    student is in, so a teacher may only preview a student who sits in none but
    hers. Her own sandbox student is always fine."""
    staff = current_staff()
    if not staff:
        return False
    if is_admin() or models.is_preview_student_of(student_id, staff['id']):
        return True
    klassen = models.get_klasse_ids_for_student(student_id)
    return bool(klassen) and klassen <= visible_klasse_ids()


def _login_guard():
    """Redirect (no session) or log out (account gone/deactivated); None = fine."""
    if 'admin_id' not in session:
        flash('Bitte melden Sie sich an.', 'warning')
        return redirect(url_for('login'))
    staff = current_staff()
    if not staff or not staff['active']:
        session.clear()
        flash('Dieses Konto ist deaktiviert.', 'warning')
        return redirect(url_for('login'))
    return None


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        refused = _login_guard()
        if refused:
            return refused
        if not is_admin():
            abort(404)
        return f(*args, **kwargs)
    decorated.access = 'admin'
    return decorated


def staff_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        refused = _login_guard()
        if refused:
            return refused
        return f(*args, **kwargs)
    decorated.access = 'staff'
    return decorated
