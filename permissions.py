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


def can_see_grading_result(result):
    """One rubric spans several classes, so a grading run has no class of its own:
    the student's result decides. Same rule as can_see_student_topic; an artifact
    handed in before the topic was assigned has no topic row, then the student's
    classes count. An unmatched login (no student) stays with the admin. The admin
    can fix the class by hand: a move or a wrongly filed student would otherwise show
    a foreign run to the new teacher (grading_result.klasse_id)."""
    ids = visible_klasse_ids()
    return ids is None or bool(ids & _grading_result_klassen(result))


def _grading_result_klassen(result):
    if result['klasse_id']:  # set by hand on the run page, wins over everything
        return {result['klasse_id']}
    student_id = result['student_id']
    if student_id is None:
        return set()
    return (models.get_klasse_ids_for_student_topic(student_id, result['task_id'])
            or models.get_klasse_ids_for_student(student_id))


def visible_grading_results(run_id):
    return [r for r in models.list_grading_results(run_id) if can_see_grading_result(r)]


def grading_run_viewers(results):
    """Reverse lookup for the admin: which active teachers see these results of a
    run, and how many of them. Same rule as can_see_grading_result, read from the
    other side. Deactivated accounts are left out, they cannot log in."""
    klassen = [_grading_result_klassen(r) for r in results]
    viewers = []
    for teacher in models.list_teachers():
        count = sum(1 for k in klassen if teacher['klasse_ids'] & k)
        if teacher['active'] and count:
            name = ' '.join(n for n in (teacher['vorname'], teacher['nachname']) if n)
            viewers.append({'name': name or teacher['username'], 'count': count})
    return viewers


def can_see_whole_grading_run(run_id):
    """Report files cover every student of the run; a class list cannot be cut down."""
    return is_admin() or all(can_see_grading_result(r) for r in models.list_grading_results(run_id))


def _grading_run_for_teacher(run, results):
    """The run's own counts and class would tell her about other classes."""
    run = dict(run, total_students=len(results),
               flagged_count=sum(1 for r in results if r['flagged']),
               zero_score_count=sum(1 for r in results if r['llm_total_score'] == 0))
    if run['klasse_id'] and not can_see_klasse(run['klasse_id']):
        run.update(klasse_id=None, klasse_name=None)
    return run


def visible_grading_runs():
    scoped = ((run, visible_grading_results(run['id'])) for run in models.list_grading_runs())
    return [dict(run if is_admin() else _grading_run_for_teacher(run, results),
                 open_count=sum(1 for r in results if models.grading_result_is_open(r)),
                 viewers=grading_run_viewers(results) if is_admin() else [])
            for run, results in scoped if results or is_admin()]


def visible_grading_audit(run_id=None):
    """Log rows of the given run, or of all runs. A teacher sees the rows about
    her students, the admin everything -- including deleted runs."""
    rows = models.list_grading_audit(run_id)
    if is_admin():
        return rows
    seen = {r['id'] for run in {row['grading_run_id'] for row in rows}
            for r in visible_grading_results(run)}
    return [row for row in rows if row['grading_result_id'] in seen]


def require_grading_run(run_id):
    """The run as this user may see it. An admin gets None for an unknown id (the
    route flashes); a teacher gets 404 for that and for a run without her students."""
    run = models.get_grading_run(run_id)
    if is_admin():
        return run
    results = visible_grading_results(run_id) if run else None
    if not results:
        abort(404)
    return _grading_run_for_teacher(run, results)


def require_grading_result(result_id):
    if is_admin():
        return
    result = models.get_grading_result(result_id)
    if not result or not can_see_grading_result(result):
        abort(404)


def require_grading_media(relpath):
    """relpath is '<run_id>/<netzwerk_id>/<file>', exactly a result's media 'file'."""
    if is_admin():
        return
    run_id = relpath.split('/')[0]
    results = visible_grading_results(int(run_id)) if run_id.isdigit() else []
    if not any(m.get('file') == relpath for r in results for m in r['media']):
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
