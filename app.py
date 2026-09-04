import os
import io
import re
import sys
import json
import uuid
import glob
import hmac
import shutil
import zipfile
import ipaddress
import sqlite3
import difflib
import traceback
import urllib.request
import urllib.error
from functools import wraps
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory, abort, Response
from flask_wtf.csrf import CSRFProtect
from flask_compress import Compress
from werkzeug.utils import secure_filename
from markupsafe import Markup
import markdown as md

import config
import models
import llm_grading
import quiz_grading
import artifact_processor
import artifact_checker
import checkpoint_questions
from utils import generate_username, generate_password, allowed_file, file_extension, material_pfad, material_filename, content_matches_extension, generate_credentials_pdf, generate_credentials_pdf_grouped, generate_name_username_pdf, generate_student_self_report_pdf, generate_class_report_pdf, generate_student_report_pdf, slugify, format_bytes, is_ip_allowed, is_within_time_window, parse_netzwerk_csv, split_tasks_by_stufe, stufe_sort_key, normalize_markdown_lists
from import_task import validate_task_structure, check_duplicate, import_task as do_import_task, overwrite_task_from_import, ValidationError

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# Secure cookie settings
# SESSION_COOKIE_SECURE: Only enable when FORCE_HTTPS is explicitly set
# This prevents redirect loops when HTTPS isn't configured yet
if os.environ.get('FORCE_HTTPS', '').lower() in ('true', '1', 'yes'):
    app.config['SESSION_COOKIE_SECURE'] = True  # Only send over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection

# CSRF protection
csrf = CSRFProtect(app)

# Gzip compression for all responses
compress = Compress(app)


# ============ Template Filters ============

@app.template_filter('markdown')
def markdown_filter(text):
    """Convert markdown text to HTML."""
    if not text:
        return ''
    text = normalize_markdown_lists(text)
    html = md.markdown(text, extensions=['nl2br', 'fenced_code', 'tables', 'sane_lists'], tab_length=3)
    return Markup(html)


@app.template_filter('slugify')
def slugify_filter(text):
    """Convert text to URL-friendly slug."""
    return slugify(text)


@app.template_filter('topic_slug')
def topic_slug(task):
    """URL slug for a topic. Seilbahn topics get 's' after the leading number (e.g. '5s-...')."""
    name = task['name']
    if task.get('is_seilbahn'):
        name = re.sub(r'^(\d+)', r'\1s', name)
    return slugify(name)


@app.template_filter('aufgabe_label')
def aufgabe_label_filter(position, subtasks):
    """Translate 1-based internal subtask position to the student-facing label.

    Driven by subtask.is_intro, not position: the subtask at `position` gets
    'E' if it's flagged is_intro, else its 1-based rank among non-intro
    subtasks up to and including that position. Needs the full `subtasks`
    list (in order) to count correctly.
    """
    sub = subtasks[position - 1] if subtasks and 1 <= position <= len(subtasks) else None
    if sub and sub.get('is_intro'):
        return 'E'
    return str(sum(1 for s in (subtasks or [])[:position] if not s.get('is_intro')))


def aufgabe_titel(beschreibung, fallback_length=80):
    """The human title of an Aufgabe, taken from its leading Markdown heading.

    Aufgabe descriptions follow the project's structured format and open with
    '### Titel' (see docs/shared/lernmanager/task_json_format.md). Anywhere that
    text is shown as a plain label the hashes have to come off first -- striptags
    only removes HTML, so '### Checkpoint Kernladung' rendered verbatim.

    Falls back to the first line for a description that has no heading.
    """
    if not beschreibung:
        return ''
    heading = re.match(r'^#{1,4}\s+(.+)', beschreibung)
    if heading:
        return heading.group(1).strip()
    return beschreibung.split('\n')[0][:fallback_length]


@app.template_filter('aufgabe_titel')
def aufgabe_titel_filter(beschreibung, fallback_length=80):
    """Template-side aufgabe_titel(); see there."""
    return aufgabe_titel(beschreibung, fallback_length)


@app.template_filter('material_filename')
def material_filename_filter(pfad):
    """Bare filename from a stored material pfad (which carries the topic folder)."""
    return material_filename(pfad)


@app.template_filter('json_lines')
def json_lines_filter(json_str):
    """Render a JSON array of strings as newline-joined text for a textarea."""
    if not json_str:
        return ''
    try:
        return '\n'.join(json.loads(json_str))
    except (ValueError, TypeError):
        return ''


@app.template_filter('b64encode')
def b64encode_filter(text):
    """Base64-encode a string for client-side email obfuscation."""
    import base64
    return base64.b64encode(text.encode()).decode()


# ============ Helpers ============

def _student_display_name():
    """Name a logged-in student sees for themselves (nav, greeting, flash).

    App-wide setting STUDENT_CLEAR_NAMES decides: clear name (vorname) or
    pseudonym (username). Both are stored in the session at login; sessions
    created before student_username existed lack that key and fall back
    to the clear name until the next login.
    """
    if app.config.get('STUDENT_CLEAR_NAMES', True):
        return session.get('student_name', '')
    return session.get('student_username') or session.get('student_name', '')


@app.context_processor
def inject_upload_accept():
    """The file picker's accept="" list, derived from config.ALLOWED_EXTENSIONS.

    Hardcoding it in the template let the form and the server-side check drift
    apart: the picker still offered only images and PDFs after the whitelist
    had grown to cover the docx/pptx templates the gates need.
    """
    return {'upload_accept': ','.join('.' + e for e in sorted(config.ALLOWED_EXTENSIONS))}


@app.context_processor
def inject_student_display_name():
    """Make student_display_name available in all templates."""
    if 'student_id' in session:
        return {'student_display_name': _student_display_name()}
    return {}


@app.context_processor
def inject_zeichenleiste():
    """Ship the whole subject-to-characters map to a logged-in student's pages.

    The map is static config and tiny; what decides whether a bar actually appears
    is the Thema in scope, looked up against this map at the moment a field is
    built. That keeps the decision at the finest grain available -- a practice run
    mixes Themen from several classes, so the bar has to come and go question by
    question, which a page-level flag could not express.

    A context processor rather than a per-route argument: the map hangs off
    base.html, and every quiz route would otherwise have to remember to pass it
    (see CLAUDE.md, "Template Context Requirements"). Admins get nothing -- they do
    not answer quizzes, and an admin previewing a student page should see the page,
    not a student-only affordance.
    """
    if 'student_id' not in session:
        return {'zeichenleiste': {}}
    return {'zeichenleiste': config.CHARACTER_SETS}


def validate_quiz_json(raw):
    """Validate and return quiz JSON string, or None if empty. Raises ValueError on invalid JSON."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f'Quiz-JSON ist ungültig: {e}')
    if not isinstance(data, dict) or 'questions' not in data:
        raise ValueError('Quiz-JSON muss ein Objekt mit "questions" sein, z.B. {"questions": [...]}')
    if not isinstance(data['questions'], list) or not data['questions']:
        raise ValueError('Quiz-JSON "questions" muss eine nicht-leere Liste sein.')
    return raw.strip()


def _connections_to_admin_fields(connections_json):
    """Parse connections_json into admin-editable textarea text.

    building_on lines: "label | unit_slug | strength" (unit/strength optional,
    omitted entirely for external/free-text-only prerequisites).
    arriving_at lines: one bullet per line.
    """
    building_on_text = ''
    arriving_at_text = ''
    if connections_json:
        try:
            connections = json.loads(connections_json)
        except (json.JSONDecodeError, TypeError):
            connections = {}
        arriving_at_text = '\n'.join(connections.get('arriving_at', []))
        lines = []
        for entry in connections.get('building_on', []):
            parts = [entry.get('label', '')]
            if entry.get('unit'):
                parts.append(entry['unit'])
                parts.append(entry.get('strength', 'hard'))
            lines.append(' | '.join(parts))
        building_on_text = '\n'.join(lines)
    return building_on_text, arriving_at_text


def _parse_connections_form(building_on_text, arriving_at_text):
    """Parse admin building_on/arriving_at textareas into a connections dict, or None if both empty."""
    building_on = []
    for line in (building_on_text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split('|')]
        entry = {'label': parts[0]}
        if len(parts) > 1 and parts[1]:
            entry['unit'] = parts[1]
        if len(parts) > 2 and parts[2] in ('hard', 'soft'):
            entry['strength'] = parts[2]
        building_on.append(entry)

    arriving_at = [line.strip() for line in (arriving_at_text or '').splitlines() if line.strip()]

    if not building_on and not arriving_at:
        return None
    connections = {}
    if building_on:
        connections['building_on'] = building_on
    if arriving_at:
        connections['arriving_at'] = arriving_at
    return connections


def _resolve_student_topic(student_id, slug):
    """Find student_task matching topic slug. Returns (task, klasse) or (None, None).

    Searches all student_task rows (active + completed, all roles) so students
    can still view completed topics' quiz results and history.
    """
    klassen = models.get_student_klassen(student_id)
    for klasse in klassen:
        tasks = models.get_all_student_tasks(student_id, klasse['id'])
        for task in tasks:
            if topic_slug(task) == slug:
                return task, klasse
    return None, None


def _resolve_subtask_by_position(subtasks, position):
    """Find subtask at 1-based position in ordered list. Returns subtask or None."""
    if 1 <= position <= len(subtasks):
        return subtasks[position - 1]
    return None


def _resolve_resume_subtask(subtasks, subtask_quiz_status):
    """Where a student should land on param-less re-entry to a topic.

    First not-yet-completed REQUIRED subtask; or, if a required subtask is
    done but its own quiz hasn't been passed yet, that subtask itself (not
    past it) so the quiz stays reachable. Optional (Zusatz) subtasks are
    skipped as resume candidates -- matching check_task_completion, which
    only counts required subtasks -- so a skipped optional subtask earlier
    in the order doesn't permanently trap re-entry there. Falls back to the
    last subtask if everything required is already done (the topic should
    be abgeschlossen by then; kept for robustness against that edge case).
    """
    for st in subtasks:
        if not st.get('required', True):
            continue
        if not st.get('erledigt'):
            return st
        if st.get('quiz_json') and not subtask_quiz_status.get(st['id'], False):
            return st
    return subtasks[-1] if subtasks else None


def _filter_quiz_for_path(quiz, student):
    """Drop quiz questions tagged with a path the student's path doesn't cover.

    Must run identically on every load of a given quiz definition (initial
    display, grading POST, and result review) so that question indices stay
    aligned across requests - see is_question_visible_for_path.
    """
    student_path = (student or {}).get('lernpfad') or 'wanderweg'
    quiz['questions'] = [
        q for q in quiz['questions']
        if models.is_question_visible_for_path(q, student_path)
    ]
    return quiz


def _build_display_quiz(quiz):
    """Transform quiz JSON (text/options) to template format (question/answers)."""
    return {
        'questions': [
            {
                'question': q['text'],
                'answers': q.get('options', []),
                'correct': q.get('correct', []),
                'image': q.get('image'),
                'type': q.get('type', 'multiple_choice'),
                'rubric': q.get('rubric', ''),           # for short_answer transparency
                'expected_answers': q.get('answers', []),  # for fill_blank transparency
                # Result page only -- this runs after grading, so handing over the
                # authored order/pairs here reveals nothing the student has not
                # already earned. The pre-answer payload comes from
                # quiz_grading.presentation(), which carries no key.
                'solution': quiz_grading.correct_answer_text(q)
                            if quiz_grading.is_interactive(q.get('type')) else '',
            }
            for q in quiz['questions']
        ]
    }


def _apply_question_order(quiz, antworten):
    """Reorder quiz questions and remap antworten keys to match the original shuffle order.

    antworten may contain '_question_order' (list of original indices in seen order).
    Returns (ordered_quiz, ordered_antworten) with keys 0..n-1 matching display order.
    """
    question_order = antworten.pop('_question_order', None)
    if not question_order:
        return quiz, antworten
    all_questions = quiz['questions']
    ordered_quiz = {'questions': [all_questions[i] for i in question_order]}
    ordered_antworten = {
        str(pos): antworten[str(orig)]
        for pos, orig in enumerate(question_order)
        if str(orig) in antworten
    }
    return ordered_quiz, ordered_antworten


# ============ Auth Decorators ============

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Bitte melden Sie sich an.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def student_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'student_id' not in session:
            flash('Bitte melden Sie sich an.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ============ Public Routes ============

@app.route('/datenschutz')
def datenschutz():
    return render_template('datenschutz.html',
        school_name=config.SCHOOL_NAME,
        school_address=config.SCHOOL_ADDRESS,
        school_email=config.SCHOOL_EMAIL,
        dsb_contact=config.DSB_CONTACT,
        privacy_authority=config.PRIVACY_AUTHORITY,
    )


# ============ Internal / Machine Routes ============
# Called by the grading service (grading-with-llm), not a browser -- shared-secret
# auth instead of session auth, CSRF-exempt (no session, no form, no cookie to forge).

@app.route('/internal/grading/results', methods=['POST'])
@csrf.exempt
def internal_grading_results():
    secret = request.headers.get('X-Grading-Callback-Secret', '')
    if not config.GRADING_SERVICE_CALLBACK_SECRET or not hmac.compare_digest(
        secret, config.GRADING_SERVICE_CALLBACK_SECRET
    ):
        return jsonify({'error': 'invalid or missing callback secret'}), 401

    payload = request.get_json(silent=True)
    if not payload or 'job_id' not in payload:
        return jsonify({'error': 'invalid payload'}), 400

    try:
        run_id = models.import_grading_callback(
            job_id=payload['job_id'],
            provider=payload.get('provider'),
            model=payload.get('model'),
            graded_at=payload.get('graded_at'),
            students=payload.get('students', []),
            rubric=payload.get('rubric'),
        )
    except ValueError as e:
        # Logged, not 500'd -- a callback for an unknown/deleted run shouldn't
        # look like a Lernmanager bug to the grading service's retry logic.
        app.logger.warning(f"grading callback rejected: {e}")
        return jsonify({'error': str(e)}), 404

    return jsonify({'status': 'ok', 'grading_run_id': run_id}), 200


_MAX_LERNPFAD_LOGINS = 500  # generous over real school-class scale (~20-90);
# past this a request signals a bug rather than a real job, and could
# otherwise pressure match_netzwerk_logins()'s `IN (?,?,?...)` SQL against
# SQLite's bound-parameter limit or spike memory (2026-08-19 security review).


@app.route('/internal/grading/lernpfad', methods=['POST'])
@csrf.exempt
def internal_grading_lernpfad():
    """
    Called by the grading service (M920x) when a job's manifest is missing
    `lernpfad` for one or more students -- confirmed 2026-08-19 this is
    every scan-folders-batch.ps1 job, which has no local Seilbahn/track
    data source at all (its manifest's `lernpfad` field was actually a
    school course code, never "seilbahn"). Reuses match_netzwerk_logins(),
    the same lookup admin_grading_match_logins() already does for the
    browser upload path -- just under machine (shared-secret) auth instead
    of an admin session, so the M920x can call it directly. Keeps
    student.lernpfad the only copy of this data anywhere (grading-with-llm
    todo.md, "scan-folders-batch.ps1 Seilbahn gap").
    """
    secret = request.headers.get('X-Grading-Callback-Secret', '')
    if not config.GRADING_SERVICE_CALLBACK_SECRET or not hmac.compare_digest(
        secret, config.GRADING_SERVICE_CALLBACK_SECRET
    ):
        return jsonify({'error': 'invalid or missing callback secret'}), 401

    payload = request.get_json(silent=True) or {}
    logins = payload.get('logins')
    if not isinstance(logins, list) or not all(isinstance(l, str) for l in logins):
        return jsonify({'error': 'logins must be a list of strings'}), 400
    if len(logins) > _MAX_LERNPFAD_LOGINS:
        return jsonify({'error': f'logins exceeds max of {_MAX_LERNPFAD_LOGINS}'}), 400

    matches = models.match_netzwerk_logins(logins)
    return jsonify({'lernpfad': {m['login']: m['lernpfad'] for m in matches if m.get('lernpfad')}})


@app.route('/internal/auth-check')
def internal_auth_check():
    """
    nginx `auth_request` target for the /grading/ proxy location (sub-phase
    2f): the browser's admin-upload POST goes straight to the grading
    service, bypassing Flask entirely for the large file body -- but nginx
    still needs to confirm the *browser* is an authenticated admin before it
    injects the shared grading-service Bearer token. nginx forwards the
    client's cookies to this subrequest automatically; we just check the
    session. 204 (not 200) so nginx has nothing to accidentally proxy back.
    """
    if 'admin_id' not in session:
        return '', 401
    return '', 204


# ============ Auth Routes ============

@app.route('/')
def index():
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))
    if 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Try admin login
        admin = models.verify_admin(username, password)
        if admin:
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            # Log login event
            models.log_analytics_event(
                event_type='login',
                user_id=admin['id'],
                user_type='admin',
                metadata={'username': admin['username']}
            )
            flash('Willkommen zurück! 👋', 'success')
            return redirect(url_for('admin_dashboard'))

        # Try student login
        student = models.verify_student(username, password)
        if student:
            session['student_id'] = student['id']
            session['student_name'] = student['vorname']
            session['student_username'] = student['username']
            # Log login event
            models.log_analytics_event(
                event_type='login',
                user_id=student['id'],
                user_type='student',
                metadata={'username': student['username']}
            )
            flash(f'Willkommen, {_student_display_name()}! 👋', 'success')
            return redirect(url_for('student_warmup'))

        flash('Benutzername oder Passwort stimmt nicht.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Auf Wiedersehen! 👋', 'info')
    return redirect(url_for('login'))


# ============ Network Access Gate ============
# Shared IP-range + time-window gate, used to restrict routes to the school
# network and/or a scheduled lesson block. Both dimensions are optional and
# admin-configurable (app_settings); a route opts into whichever it needs.

_TRUSTED_PROXY_ADDRS = {'127.0.0.1', '::1'}


def _get_client_ip():
    """Real client IP behind nginx (X-Real-IP). Only trusted when the immediate
    connection is from the local reverse proxy (deploy/nginx.conf proxies to
    127.0.0.1:8081) -- otherwise a direct request to the app port could spoof
    the header to bypass IP-range gates (school_only materials, checkpoints)."""
    if request.remote_addr in _TRUSTED_PROXY_ADDRS:
        return request.headers.get('X-Real-IP') or request.remote_addr
    return request.remote_addr


def _client_in_school_network():
    """True if the current request's client IP falls inside the shared
    network_gate_ip_ranges setting (admin dashboard 'Netzwerk-Gate')."""
    ip_ranges = models.get_setting('network_gate_ip_ranges', '')
    return is_ip_allowed(_get_client_ip(), ip_ranges)


def _school_gate_ok(row):
    """Shared network gate for any row with a school_only column (subtask
    checkpoints, materials). Returns True if the row is either not restricted,
    or the current request's client is inside the school network."""
    if not row['school_only']:
        return True
    return _client_in_school_network()


# ============ Admin Dashboard ============

def get_disk_status(percent_used):
    """Map disk usage percent to a (label, css_class) status for the dashboard widget."""
    if percent_used >= 85:
        return ("Kritisch", "critical")
    elif percent_used >= 70:
        return ("Wird langsam knapp", "warn")
    else:
        return ("OK", "ok")


@app.route('/admin')
@admin_required
def admin_dashboard():
    klassen = models.get_all_klassen()
    tasks = models.get_all_tasks()

    disk_total, _, disk_free = shutil.disk_usage(config.BASE_DIR)
    disk_used = disk_total - disk_free
    disk_percent = round(disk_used / disk_total * 100, 1)
    disk_status_label, disk_status_class = get_disk_status(disk_percent)

    # Filter classes for "Unterricht heute" based on schedule
    today_weekday = datetime.today().weekday()  # 0=Monday, 6=Sunday
    klassen_heute = []
    for klasse in klassen:
        schedule = models.get_class_schedule(klasse['id'])
        if schedule and schedule['weekday'] == today_weekday:
            klassen_heute.append(klasse)

    return render_template('admin/dashboard.html', klassen=klassen, tasks=tasks,
                          klassen_heute=klassen_heute,
                          disk_total=format_bytes(disk_total), disk_used=format_bytes(disk_used),
                          disk_free=format_bytes(disk_free), disk_percent=disk_percent,
                          disk_status_label=disk_status_label, disk_status_class=disk_status_class)


@app.route('/admin/einstellungen')
@admin_required
def admin_einstellungen():
    log_page_views = models.get_bool_setting('log_page_views', default=True)
    student_clear_names = models.get_bool_setting('student_clear_names', default=True)

    # Network access gate settings (IP ranges + time window)
    network_gate_ip_ranges = models.get_setting('network_gate_ip_ranges', '')
    network_gate_start_time = models.get_setting('network_gate_start_time', '')
    network_gate_end_time = models.get_setting('network_gate_end_time', '')

    return render_template('admin/einstellungen.html', log_page_views=log_page_views,
                          student_clear_names=student_clear_names,
                          network_gate_ip_ranges=network_gate_ip_ranges,
                          network_gate_start_time=network_gate_start_time,
                          network_gate_end_time=network_gate_end_time)


@app.route('/admin/settings', methods=['POST'])
@admin_required
def admin_update_settings():
    """Update application settings."""
    log_page_views = 'log_page_views' in request.form
    models.set_bool_setting('log_page_views', log_page_views)

    student_clear_names = 'student_clear_names' in request.form
    models.set_bool_setting('student_clear_names', student_clear_names)

    # Update cached values
    app.config['LOG_PAGE_VIEWS'] = log_page_views
    app.config['STUDENT_CLEAR_NAMES'] = student_clear_names

    flash('Einstellungen gespeichert. ✅', 'success')
    return redirect(url_for('admin_einstellungen'))


@app.route('/admin/settings/netzwerk-gate', methods=['POST'])
@admin_required
def admin_update_network_gate():
    """Update IP-range and time-window settings for the shared network access gate."""
    ip_ranges = request.form.get('network_gate_ip_ranges', '').strip()
    start_time = request.form.get('network_gate_start_time', '').strip()
    end_time = request.form.get('network_gate_end_time', '').strip()

    for entry in re.split(r'[,\n]', ip_ranges):
        entry = entry.strip()
        if not entry:
            continue
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            flash(f'Ungültiger IP-Bereich: "{entry}". Nichts gespeichert.', 'danger')
            return redirect(url_for('admin_einstellungen'))

    if bool(start_time) != bool(end_time):
        flash('Start- und Endzeit müssen beide gesetzt sein (oder beide leer). Nichts gespeichert.', 'danger')
        return redirect(url_for('admin_einstellungen'))
    for t in (start_time, end_time):
        if t:
            try:
                datetime.strptime(t, '%H:%M')
            except ValueError:
                flash(f'Ungültige Uhrzeit: "{t}". Format HH:MM. Nichts gespeichert.', 'danger')
                return redirect(url_for('admin_einstellungen'))

    models.set_setting('network_gate_ip_ranges', ip_ranges)
    models.set_setting('network_gate_start_time', start_time)
    models.set_setting('network_gate_end_time', end_time)

    flash('Netzwerk-Einstellungen gespeichert. ✅', 'success')
    return redirect(url_for('admin_einstellungen'))


# ============ Admin: Klassen ============

@app.route('/admin/klassen')
@admin_required
def admin_klassen():
    klassen = models.get_all_klassen()
    return render_template('admin/klassen.html', klassen=klassen)


@app.route('/admin/klasse/neu', methods=['POST'])
@admin_required
def admin_klasse_neu():
    name = request.form['name'].strip()
    if name:
        models.create_klasse(name)
        flash(f'Klasse "{name}" erstellt. ✅', 'success')
    return redirect(url_for('admin_klassen'))


@app.route('/admin/klasse/<int:klasse_id>')
@admin_required
def admin_klasse_detail(klasse_id):
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    students = models.get_students_in_klasse(klasse_id)
    tasks = models.get_all_tasks()
    unterricht = models.get_klasse_unterricht(klasse_id)
    schedule = models.get_class_schedule(klasse_id)

    # Enrich students with queue position (avoids N+1 queries)
    queue = models.get_topic_queue(klasse_id)
    queue_lookup = {q['task_id']: (q['position'], len(queue)) for q in queue}
    for s in students:
        if s.get('task_id') and s['task_id'] in queue_lookup:
            s['queue_pos'], s['queue_total'] = queue_lookup[s['task_id']]

    sidequests = models.get_sidequests_for_klasse(klasse_id)
    practice_unlocked_ids = models.get_practice_unlocked_task_ids(klasse_id)
    andere_klassen = [k for k in models.get_all_klassen() if k['id'] != klasse_id]
    themen_exact, themen_other = split_tasks_by_stufe(tasks, [klasse.get('klassenstufe')])
    return render_template('admin/klasse_detail.html', klasse=klasse, students=students,
                           tasks=tasks, themen_exact=themen_exact, themen_other=themen_other,
                           unterricht=unterricht, schedule=schedule,
                           has_queue=bool(queue), sidequests=sidequests,
                           practice_unlocked_ids=practice_unlocked_ids,
                           andere_klassen=andere_klassen)


@app.route('/admin/klasse/<int:klasse_id>/namen-benutzernamen-pdf')
@admin_required
def admin_klasse_namen_benutzernamen_pdf(klasse_id):
    """Download a PDF with student names and usernames (no passwords)."""
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    students = models.get_students_in_klasse(klasse_id)

    pdf_buffer = generate_name_username_pdf(students, klasse['name'])

    return Response(
        pdf_buffer.getvalue(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename=namen_benutzernamen_{klasse["name"]}.pdf'
        }
    )


def _grading_service_health():
    """GET the grading service's unauthenticated /health over WireGuard,
    server-side (never exposes GRADING_SERVICE_URL/_TOKEN to the browser).
    Returns True/False; 'not configured' is reported separately by the caller."""
    if not config.GRADING_SERVICE_URL:
        return None
    try:
        with urllib.request.urlopen(f"{config.GRADING_SERVICE_URL}/health", timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _grading_job_status(job_id):
    """GET the grading service's authenticated /jobs/<id> server-side (same
    never-expose-token-to-browser rule as _grading_service_health). Returns
    the parsed job dict ({'status', 'progress', 'error', ...}) or a dict with
    an 'offline' key if the service can't be reached -- callers branch on
    that instead of raising, since a job stuck 'pending import' because the
    M920x is asleep is an expected, not exceptional, state here."""
    if not config.GRADING_SERVICE_URL:
        return {'offline': True}
    req = urllib.request.Request(
        f"{config.GRADING_SERVICE_URL}/jobs/{job_id}",
        headers={'Authorization': f'Bearer {config.GRADING_SERVICE_TOKEN}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return {'offline': True}


def _grading_job_retry(job_id):
    """POST {job_id}/retry server-side. Returns (ok, message) for the caller
    to flash -- 409 means the job wasn't in 'failed' status (stale UI, e.g.
    someone already retried it or it finished since the page loaded), which
    is a normal race here, not a bug to surface as a 500."""
    if not config.GRADING_SERVICE_URL:
        return False, 'Bewertungsdienst nicht konfiguriert.'
    req = urllib.request.Request(
        f"{config.GRADING_SERVICE_URL}/jobs/{job_id}/retry",
        method='POST',
        headers={'Authorization': f'Bearer {config.GRADING_SERVICE_TOKEN}'},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True, 'Job erneut in die Warteschlange gestellt.'
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return False, 'Job ist nicht mehr im Status "failed" (evtl. schon läuft er wieder). Seite neu laden.'
        return False, f'Bewertungsdienst antwortete mit Fehler {e.code}.'
    except (urllib.error.URLError, OSError, TimeoutError):
        return False, 'Bewertungsdienst nicht erreichbar.'


@app.route('/admin/grading/health')
@admin_required
def admin_grading_health():
    """AJAX: powers the 'Grading service offline' banner on the upload page
    (grading-service-deployment.md §Phase 2 -- M920x is a home machine, this
    must fail visibly rather than obscurely)."""
    status = _grading_service_health()
    if status is None:
        return jsonify({'configured': False, 'online': False})
    return jsonify({'configured': True, 'online': status})


@app.route('/admin/bewertung/netzwerk-ids', methods=['GET', 'POST'])
@admin_required
def admin_bewertung_netzwerk_ids():
    """CSV-based netzwerk_id matcher: upload the school's real roster export
    (Nachname, Vorname, Login), Lernmanager matches it against students by
    name and reports differences for manual review -- see
    models.diff_netzwerk_ids() (ports grading-with-llm's
    scripts/validate_student_ids.py mismatch-reporting approach). Nothing is
    written until the admin submits the review form below."""
    diff = None
    klassenstufen_diff = None
    klassen_kurs_diff = None
    student_enrollment_diff = None
    if request.method == 'POST':
        file = request.files.get('roster_csv')
        if not file or not file.filename:
            flash('Bitte eine CSV-Datei auswählen.', 'warning')
        else:
            try:
                csv_rows = parse_netzwerk_csv(file.stream)
                diff = models.diff_netzwerk_ids(csv_rows)
                klassenstufen_diff = models.diff_klassenstufen(csv_rows)
                klassen_kurs_diff = models.diff_klassen_kurs(csv_rows)
                student_enrollment_diff = models.diff_student_enrollment(csv_rows, klassen_kurs_diff)
            except ValueError as e:
                flash(f'Fehler beim Einlesen der CSV: {e}', 'danger')

    return render_template(
        'admin/bewertung_netzwerk_ids.html', diff=diff,
        klassenstufen_diff=klassenstufen_diff,
        klassen_kurs_diff=klassen_kurs_diff,
        student_enrollment_diff=student_enrollment_diff,
    )


@app.route('/admin/bewertung/netzwerk-ids/apply', methods=['POST'])
@admin_required
def admin_bewertung_netzwerk_ids_apply():
    """Writes the netzwerk_id corrections the admin checked off on the diff
    report. Runs one update at a time so a single collision (another
    student already has that ID) doesn't roll back the whole batch."""
    applied, conflicts = 0, []
    for change in request.form.getlist('change'):
        student_id, _, login = change.partition(':')
        if not student_id.isdigit() or not login:
            continue
        try:
            models.update_student_netzwerk_id(int(student_id), login)
            applied += 1
        except sqlite3.IntegrityError:
            conflicts.append(login)

    name_matches_applied = 0
    for value in request.form.getlist('name_match'):
        student_id, _, rest = value.partition('|')
        nachname, _, rest = rest.partition('|')
        vorname, _, login = rest.partition('|')
        if not student_id.isdigit() or not nachname or not vorname:
            continue
        models.update_student_name(int(student_id), nachname, vorname)
        try:
            models.update_student_netzwerk_id(int(student_id), login)
        except sqlite3.IntegrityError:
            conflicts.append(login)
        name_matches_applied += 1

    if applied:
        flash(f'{applied} Netzwerk-ID(s) aktualisiert. ✅', 'success')
    if name_matches_applied:
        flash(f'{name_matches_applied} Namensabweichung(en) übernommen. ✅', 'success')
    if conflicts:
        flash(
            f'{len(conflicts)} übersprungen wegen Konflikt (Login bereits vergeben): '
            f'{", ".join(conflicts)}', 'danger'
        )
    if not applied and not name_matches_applied and not conflicts:
        flash('Keine Änderungen ausgewählt.', 'warning')

    return redirect(url_for('admin_bewertung_netzwerk_ids'))


@app.route('/admin/bewertung/netzwerk-ids/roster-apply', methods=['POST'])
@admin_required
def admin_bewertung_roster_apply():
    """Writes the class links/creations and student creates/moves the admin
    checked off on the roster-sync diff report (extends the netzwerk-ids
    page -- see models.diff_klassen_kurs()/diff_student_enrollment()).

    Order matters within this one POST: classes first (link existing ones,
    create new ones), then students -- a student row targeting a
    just-created class needs that class's id to already exist. Each row is
    still applied independently (try/except per row) so one bad row
    doesn't roll back the rest, same pattern as the netzwerk-id apply
    route above.
    """
    klassen_applied, klassen_conflicts = 0, []

    for value in request.form.getlist('klasse_link'):
        klasse_id, _, kurs_code = value.partition(':')
        if not klasse_id.isdigit() or not kurs_code:
            continue
        try:
            models.set_klasse_kurs_code(int(klasse_id), kurs_code)
            klassen_applied += 1
        except sqlite3.IntegrityError:
            klassen_conflicts.append(kurs_code)

    for kurs_code in request.form.getlist('klasse_create'):
        stufe = request.form.get(f'klasse_create_stufe__{kurs_code}', '').strip()
        name = request.form.get(f'klasse_create_name__{kurs_code}', '').strip()
        if not name:
            continue
        try:
            klasse_id = models.create_klasse(name)
            models.set_klasse_kurs_code(klasse_id, kurs_code)
            if stufe.isdigit():
                models.update_klasse_klassenstufe(klasse_id, int(stufe))
            klassen_applied += 1
        except sqlite3.IntegrityError:
            klassen_conflicts.append(kurs_code)

    if klassen_applied:
        flash(f'{klassen_applied} Klasse(n) verknüpft/erstellt. ✅', 'success')
    if klassen_conflicts:
        flash(
            f'{len(klassen_conflicts)} Klassen-Zuordnung(en) übersprungen wegen Konflikt: '
            f'{", ".join(klassen_conflicts)}', 'danger'
        )

    students_applied, students_skipped = 0, []
    created_students = []
    existing_usernames = models.get_existing_usernames()
    existing_netzwerk_ids = models.get_existing_netzwerk_ids()

    for value in request.form.getlist('student_create'):
        nachname, _, rest = value.partition('|')
        vorname, _, rest = rest.partition('|')
        netzwerk_id, _, kurs_code = rest.partition('|')
        if not nachname or not vorname or not netzwerk_id or not kurs_code:
            continue
        klasse = models.get_klasse_by_kurs_code(kurs_code)
        if klasse is None:
            students_skipped.append(f'{nachname}, {vorname} (Klasse {kurs_code} nicht angelegt)')
            continue
        try:
            username = generate_username(existing_usernames, vorname, nachname)
            existing_usernames.add(username)
            password = generate_password()
            student_id = models.create_student(nachname, vorname, username, password, netzwerk_id=netzwerk_id)
            existing_netzwerk_ids.add(netzwerk_id)
            models.add_student_to_klasse(student_id, klasse['id'])
            students_applied += 1
            created_students.append({
                'nachname': nachname, 'vorname': vorname,
                'username': username, 'password': password,
                'klasse_name': klasse['name'],
            })
        except sqlite3.IntegrityError:
            students_skipped.append(f'{nachname}, {vorname} (Netzwerk-ID {netzwerk_id} bereits vergeben)')

    for value in request.form.getlist('student_move'):
        student_id, _, rest = value.partition(':')
        from_klasse_id, _, kurs_code = rest.partition(':')
        if not student_id.isdigit() or not from_klasse_id.isdigit() or not kurs_code:
            continue
        klasse = models.get_klasse_by_kurs_code(kurs_code)
        if klasse is None:
            students_skipped.append(f'Schüler #{student_id} (Klasse {kurs_code} nicht angelegt)')
            continue
        models.move_student_to_klasse(int(student_id), int(from_klasse_id), klasse['id'])
        students_applied += 1

    if students_applied:
        flash(f'{students_applied} Schüler-Zuordnung(en) übernommen. ✅', 'success')
    if students_skipped:
        flash(
            f'{len(students_skipped)} übersprungen: {", ".join(students_skipped)}', 'danger'
        )
    if not klassen_applied and not klassen_conflicts and not students_applied and not students_skipped:
        flash('Keine Änderungen ausgewählt.', 'warning')

    if created_students:
        groups = {}
        for s in created_students:
            groups.setdefault(s['klasse_name'], []).append(s)
        grouped = [(name, groups[name]) for name in sorted(groups)]
        pdf_buffer = generate_credentials_pdf_grouped(grouped)
        return Response(
            pdf_buffer.getvalue(),
            mimetype='application/pdf',
            headers={'Content-Disposition': 'attachment; filename=zugangsdaten_schuelerdaten_abgleich.pdf'}
        )

    return redirect(url_for('admin_bewertung_netzwerk_ids'))


@app.route('/admin/grading/upload')
@admin_required
def admin_grading_upload():
    """
    Class-agnostic upload page (multi-class + chunked upload redesign,
    todo.md § Graded Artifacts 2026-08-17). Replaces the old per-class
    /admin/klasse/<id>/grading/upload: a single scan-folders zip can contain
    students from several classes, or a class only the teacher's local
    machine knows about (a grade-wide "5"/"6" scan), so the page no longer
    pre-builds a manifest from one class's roster server-side. Instead the
    browser parses the zip client-side and calls
    /admin/grading/match-logins to resolve whatever logins it finds against
    the global roster -- see that route and grading_upload.html.
    """
    tasks = models.list_tasks_with_graded_artifact()
    for t in tasks:
        t['grading_keyword'] = models.get_task_grading_keyword(t['id'])
    tasks = [t for t in tasks if t['grading_keyword']]

    return render_template(
        'admin/grading_upload.html', tasks=tasks,
        service_online=_grading_service_health(),
    )


@app.route('/admin/grading/match-logins', methods=['POST'])
@admin_required
def admin_grading_match_logins():
    """
    AJAX: the browser has already unzipped the archive client-side and
    normalized the top-level folder names (same umlaut-fold rule as
    scan-folders' ConvertTo-NormalizedLogin, so both sides agree) -- this
    resolves those logins against the *global* student roster and returns
    only the matches. Deliberately not "hand the browser the whole roster
    and let it filter locally": keeps real names off the page for students
    who aren't even in this zip (grading-service-deployment.md §5's
    manifest shape -- names travel only for students actually being graded).
    """
    payload = request.get_json(silent=True) or {}
    logins = payload.get('logins')
    if not isinstance(logins, list) or not all(isinstance(l, str) for l in logins):
        return jsonify({'error': 'logins must be a list of strings'}), 400

    matches = models.match_netzwerk_logins(logins)
    matched_logins = {m['login'] for m in matches}
    unmatched = [l for l in logins if l not in matched_logins]
    return jsonify({'matches': matches, 'unmatched': unmatched})


@app.route('/admin/grading/upload/complete', methods=['POST'])
@admin_required
def admin_grading_upload_complete():
    """
    Called by the upload page's JS *after* the browser's direct chunked
    upload to the grading service (nginx-proxied straight to the M920x,
    bypassing Flask -- see docs/shared/grading-with-llm/grading-service-
    deployment.md §4) has already returned a job_id. This tiny JSON request
    is the only grading-service traffic that goes through Flask --
    "Lernmanager receives only the job_id" (spec §10 Phase 2). klasse_id is
    intentionally not recorded here (a run can span several classes now) --
    classes touched are derived per-result via student_klasse when needed.
    """
    payload = request.get_json(silent=True) or {}
    job_id = payload.get('job_id')
    task_id = payload.get('task_id')
    rubric = payload.get('rubric')
    provider = payload.get('provider')
    total_students = payload.get('students', 0)
    if not job_id or not task_id or not rubric or not provider:
        return jsonify({'error': 'job_id, task_id, rubric and provider are required'}), 400

    run_id = models.create_grading_run(
        job_id=job_id, klasse_id=None, task_id=task_id, rubric=rubric,
        provider=provider, model=None, total_students=total_students,
    )
    return jsonify({'grading_run_id': run_id}), 201


@app.route('/admin/grading/runs')
@admin_required
def admin_grading_runs():
    """Overview list of grading_run rows -- the entry point into
    grading_run_detail, which previously had no link pointing at it from
    anywhere in the nav (found while building the multi-class redesign)."""
    return render_template('admin/grading_runs.html', runs=models.list_grading_runs())


# --- Page A: grading_run_detail (teacher-review-ui.md §2 -- class-level view) ---

@app.route('/admin/grading-run/<int:run_id>')
@admin_required
def admin_grading_run_detail(run_id):
    run = models.get_grading_run(run_id)
    if not run:
        flash('Bewertungslauf nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))

    results = models.list_grading_results(run_id)
    non_submitters = [r for r in results if models.is_non_submitter_result(r)]
    reviewable = [r for r in results if not models.is_non_submitter_result(r)]

    # Bulk-release partition (teacher-review-ui.md §4): results with an
    # already-active sibling for the same (student, task) need a supersede
    # decision first, everyone else can go in one click.
    no_conflict = []
    needs_decision = []
    for r in reviewable:
        if r['status'] not in ('imported', 'under_review', 'corrected'):
            continue
        active = models.get_active_grading_result(r['student_id'], run['task_id']) if r['student_id'] else None
        if active and active['id'] != r['id']:
            needs_decision.append(r)
        else:
            no_conflict.append(r)

    # graded_at is only set once the results callback lands (models.py
    # import_grading_callback) -- until then, the job is still on the
    # service and the only source of truth for its status is the service
    # itself (no local status column, see task_plan.md § Decisions).
    job_status = _grading_job_status(run['job_id']) if not run['graded_at'] else None

    return render_template(
        'admin/grading_run_detail.html', run=run, results=results, reviewable=reviewable,
        non_submitters=non_submitters, no_conflict=no_conflict, needs_decision=needs_decision,
        override_rate=models.get_grading_run_override_rate(run_id), job_status=job_status,
    )


@app.route('/admin/grading-run/<int:run_id>/retry-job', methods=['POST'])
@admin_required
def admin_grading_run_retry_job(run_id):
    run = models.get_grading_run(run_id)
    if not run:
        flash('Bewertungslauf nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))

    ok, message = _grading_job_retry(run['job_id'])
    flash(message, 'success' if ok else 'danger')
    return redirect(url_for('admin_grading_run_detail', run_id=run_id))


@app.route('/admin/grading-run/<int:run_id>/discard', methods=['POST'])
@admin_required
def admin_grading_run_discard(run_id):
    models.discard_grading_run(run_id)
    flash('Bewertungslauf verworfen (bereits freigegebene Ergebnisse bleiben sichtbar).', 'success')
    models.maybe_auto_purge_grading_run(run_id)
    return redirect(url_for('admin_grading_run_detail', run_id=run_id))


@app.route('/admin/grading-run/<int:run_id>/release-bulk', methods=['POST'])
@admin_required
def admin_grading_run_release_bulk(run_id):
    run = models.get_grading_run(run_id)
    released = skipped = 0
    for r in models.list_grading_results(run_id):
        if r['status'] not in ('imported', 'under_review', 'corrected'):
            continue
        try:
            models.release_grading_result(r['id'], session['admin_id'])
            released += 1
        except ValueError:
            skipped += 1
    flash(f'{released} Ergebnis(se) freigegeben. {skipped} übersprungen (Konflikt oder offene Prüfung).',
          'success' if released else 'warning')
    models.maybe_auto_purge_grading_run(run_id)
    return redirect(url_for('admin_grading_run_detail', run_id=run_id))


@app.route('/admin/grading-run/<int:run_id>/purge-media', methods=['POST'])
@admin_required
def admin_grading_run_purge_media(run_id):
    """Manual early purge (spec §7's retention rule), independent of whether
    the run is fully settled yet -- a teacher may want to force cleanup."""
    models.purge_grading_run_media(run_id)
    flash('Medien gelöscht.', 'success')
    return redirect(url_for('admin_grading_run_detail', run_id=run_id))


@app.route('/admin/grading-result/<int:result_id>/confirm', methods=['POST'])
@admin_required
def admin_grading_result_confirm(result_id):
    """One-click release for non-submitters (teacher-review-ui.md §4) --
    no media to review, routing them through Page B is pure friction."""
    result = models.get_grading_result(result_id)
    if not result:
        flash('Ergebnis nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    try:
        models.release_grading_result(result_id, session['admin_id'])
        flash('Bestätigt.', 'success')
    except ValueError as e:
        flash(f'Konnte nicht bestätigt werden: {e}', 'danger')
    models.maybe_auto_purge_grading_run(result['grading_run_id'])
    return redirect(url_for('admin_grading_run_detail', run_id=result['grading_run_id']))


@app.route('/admin/grading-result/<int:result_id>/discard', methods=['POST'])
@admin_required
def admin_grading_result_discard(result_id):
    result = models.get_grading_result(result_id)
    if not result:
        flash('Ergebnis nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    models.discard_grading_result(result_id)
    flash('Verworfen.', 'success')
    models.maybe_auto_purge_grading_run(result['grading_run_id'])
    return redirect(url_for('admin_grading_run_detail', run_id=result['grading_run_id']))


# --- Page B: grading_review (teacher-review-ui.md §3-5 -- per-student review flow) ---

@app.route('/admin/grading-result/<int:result_id>/review', methods=['GET', 'POST'])
@admin_required
def admin_grading_result_review(result_id):
    result = models.get_grading_result(result_id)
    if not result:
        flash('Ergebnis nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    run = models.get_grading_run(result['grading_run_id'])

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        if action == 'skip':
            # Advances without writing anything (teacher-review-ui.md §4) --
            # distinct from Speichern & Weiter, which does persist edits first.
            nxt = models.get_next_in_review_queue(run['id'], result_id)
            if nxt:
                return redirect(url_for('admin_grading_result_review', result_id=nxt['id']))
            return redirect(url_for('admin_grading_run_detail', run_id=run['id']))

        criteria = []
        for i, c in enumerate(result['criteria']):
            raw = request.form.get(f'teacher_score_{i}')
            try:
                teacher_score = float(raw) if raw not in (None, '') else c.get('llm_score')
            except ValueError:
                teacher_score = c.get('llm_score')
            entry = dict(c)
            entry['teacher_score'] = teacher_score
            if c.get('review_required'):
                entry['confirmed'] = request.form.get(f'confirmed_{i}') == 'on'
            criteria.append(entry)
        models.save_grading_result_review(result_id, criteria)

        if action == 'save_next':
            nxt = models.get_next_in_review_queue(run['id'], result_id)
            if nxt:
                return redirect(url_for('admin_grading_result_review', result_id=nxt['id']))
            flash('Prüfung abgeschlossen -- zurück zur Übersicht.', 'success')
            return redirect(url_for('admin_grading_run_detail', run_id=run['id']))

        flash('Gespeichert.', 'success')
        return redirect(url_for('admin_grading_result_review', result_id=result_id))

    result = models.get_grading_result(result_id)  # re-fetch: GET always shows latest saved state
    queue = models.get_grading_run_review_queue(run['id'])
    queue_ids = [r['id'] for r in queue]
    position = queue_ids.index(result_id) + 1 if result_id in queue_ids else None
    remaining_flagged = sum(
        1 for r in queue if r['id'] != result_id and any(
            (c.get('review_required') and not c.get('confirmed')) or c.get('llm_score') == 0
            for c in r['criteria']
        )
    )
    prev_result = queue[queue_ids.index(result_id) - 1] if position and position > 1 else None

    supersede_conflict = None
    if result['student_id']:
        active = models.get_active_grading_result(result['student_id'], run['task_id'])
        if active and active['id'] != result_id:
            supersede_conflict = active

    return render_template(
        'admin/grading_review.html', result=result, run=run, position=position,
        queue_total=len(queue), remaining_flagged=remaining_flagged,
        prev_result=prev_result, supersede_conflict=supersede_conflict,
    )


@app.route('/admin/grading-result/<int:result_id>/supersede', methods=['GET', 'POST'])
@admin_required
def admin_grading_result_supersede(result_id):
    """
    Resolve a supersede conflict (spec §7): two grading_results exist for the
    same (student, artifact), one already 'active'. Side-by-side comparison,
    one radio choice picks the winner -- never a silent bulk-overwrite of an
    existing active run.
    """
    challenger = models.get_grading_result(result_id)
    if not challenger:
        flash('Ergebnis nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    run = models.get_grading_run(challenger['grading_run_id'])
    active = models.get_active_grading_result(challenger['student_id'], run['task_id']) if challenger['student_id'] else None

    if not active or active['id'] == result_id:
        flash('Kein Konflikt (mehr) für dieses Ergebnis.', 'warning')
        return redirect(url_for('admin_grading_run_detail', run_id=run['id']))

    if request.method == 'POST':
        winner = request.form.get('winner')
        active_run_id = active['grading_run_id']
        if winner == 'challenger':
            models.supersede_grading_result(active['id'], result_id)
            models.release_grading_result(result_id, session['admin_id'])
            flash('Neue Bewertung übernommen.', 'success')
        else:
            models.discard_grading_result(result_id)
            flash('Bestehende Bewertung behalten.', 'success')
        models.maybe_auto_purge_grading_run(run['id'])
        models.maybe_auto_purge_grading_run(active_run_id)
        return redirect(url_for('admin_grading_run_detail', run_id=run['id']))

    return render_template('admin/grading_supersede.html', challenger=challenger, active=active, run=run)


@app.route('/grading-medien/<path:relpath>')
@admin_required
def download_grading_media(relpath):
    """Serve a graded image copied locally at import time (models._copy_grading_media,
    teacher-review-ui.md §6) -- admin-gated, inline (not an attachment) so it
    renders in Page B's gallery. relpath is '<run_id>/<netzwerk_id>/<filename>',
    exactly the 'file' field stored on each grading_result media entry."""
    upload_dir = os.path.abspath(models._grading_upload_dir())
    directory, filename = os.path.split(relpath)
    full_dir = os.path.abspath(os.path.join(upload_dir, directory))
    # os.path.abspath collapses any '..' before this check runs -- reject
    # anything that resolved outside upload_dir, same class of guard as
    # send_from_directory's own, applied before we even build the path.
    if os.path.commonpath([upload_dir, full_dir]) != upload_dir:
        abort(404)
    if not os.path.isfile(os.path.join(full_dir, filename)):
        abort(404)
    return send_from_directory(full_dir, filename, as_attachment=False)


@app.route('/admin/klasse/<int:klasse_id>/llm-feedback', methods=['POST'])
@admin_required
def admin_klasse_llm_feedback_toggle(klasse_id):
    """Toggle LLM artifact feedback for a class."""
    enabled = request.form.get('enabled') == '1'
    models.set_klasse_llm_feedback(klasse_id, enabled)
    state = 'aktiviert' if enabled else 'deaktiviert'
    flash(f'KI-Artefakt-Feedback {state}.', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/transparenzmodus', methods=['POST'])
@admin_required
def admin_klasse_transparency_mode(klasse_id):
    """Set class-level LLM transparency override (None/0/1)."""
    value = request.form.get('mode')
    mode = None if value == '' else int(value)
    models.set_klasse_transparency_mode(klasse_id, mode)
    labels = {'': 'auf Schüler-Einstellung', '0': 'deaktiviert', '1': 'aktiviert'}
    flash(f'KI-Transparenzmodus {labels.get(value, "gesetzt")}.', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/abgeschlossene-themen', methods=['POST'])
@admin_required
def admin_klasse_show_completed_topics(klasse_id):
    """Toggle the 'Abgeschlossene Themen' list on this class's student dashboards."""
    show = request.form.get('show') == '1'
    models.set_klasse_show_completed_topics(klasse_id, show)
    state = 'sichtbar' if show else 'ausgeblendet'
    flash(f'Abgeschlossene Themen jetzt {state}.', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/loeschen', methods=['POST'])
@admin_required
def admin_klasse_loeschen(klasse_id):
    klasse = models.get_klasse(klasse_id)
    if klasse:
        models.delete_klasse(klasse_id)
        flash(f'Klasse "{klasse["name"]}" gelöscht.', 'success')
    return redirect(url_for('admin_klassen'))


@app.route('/admin/klasse/<int:klasse_id>/umbenennen', methods=['POST'])
@admin_required
def admin_klasse_umbenennen(klasse_id):
    name = request.form.get('name', '').strip()
    if not name:
        flash('Klassenname darf nicht leer sein.', 'danger')
    else:
        models.update_klasse_name(klasse_id, name)
        flash(f'Klasse umbenannt zu „{name}“. ✅', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/klassenstufe-setzen', methods=['POST'])
@admin_required
def admin_klasse_klassenstufe(klasse_id):
    raw = request.form.get('klassenstufe', '').strip()
    if not raw:
        models.update_klasse_klassenstufe(klasse_id, None)
        flash('Klassenstufe entfernt.', 'success')
    elif raw.isdigit():
        models.update_klasse_klassenstufe(klasse_id, int(raw))
        flash(f'Klassenstufe auf {raw} gesetzt. ✅', 'success')
    else:
        flash('Klassenstufe muss eine Zahl sein.', 'danger')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/schueler-verschieben-batch', methods=['POST'])
@admin_required
def admin_klasse_schueler_verschieben_batch(klasse_id):
    """Move multiple selected students from this class to another in one go
    (prep for school-year transitions: reshuffling/splitting/merging classes)."""
    to_klasse_id = request.form.get('to_klasse', type=int)
    student_ids = request.form.getlist('student_ids', type=int)
    to_klasse = models.get_klasse(to_klasse_id) if to_klasse_id else None
    if not to_klasse or not student_ids:
        flash('Bitte Zielklasse und mindestens einen Schüler auswählen.', 'danger')
        return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))

    for student_id in student_ids:
        models.move_student_to_klasse(student_id, klasse_id, to_klasse_id)
    flash(f'{len(student_ids)} Schüler nach „{to_klasse["name"]}“ verschoben. ✅', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/alle-schueler-loeschen', methods=['POST'])
@admin_required
def admin_klasse_alle_schueler_loeschen(klasse_id):
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    confirmation = request.form.get('confirm_name', '').strip()
    if confirmation != klasse['name']:
        flash('Bestätigung fehlgeschlagen — Klassenname stimmt nicht überein.', 'danger')
        return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))
    _unlink_artifact_files(models.delete_all_students_in_klasse(klasse_id))
    flash(f'Alle Schülerdaten der Klasse „{klasse["name"]}“ wurden gelöscht (DSGVO).', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/schedule', methods=['POST'])
@admin_required
def admin_klasse_schedule(klasse_id):
    weekday_str = request.form.get('weekday')
    if weekday_str:
        weekday = int(weekday_str)
        models.set_class_schedule(klasse_id, weekday)
        weekday_names = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
        flash(f'Wöchentlicher Termin: {weekday_names[weekday]} ✅', 'success')
    else:
        models.delete_class_schedule(klasse_id)
        flash('Wöchentlicher Termin entfernt.', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/bericht')
@admin_required
def admin_klasse_bericht(klasse_id):
    """Generate and download class progress report PDF."""
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Get report data
    report_data = models.get_report_data_for_class(klasse_id, date_from=date_from, date_to=date_to)

    if not report_data:
        flash('Klasse nicht gefunden.', 'error')
        return redirect(url_for('admin_klassen'))

    # Generate PDF
    pdf_buffer = generate_class_report_pdf(report_data, date_from=date_from, date_to=date_to)

    # Prepare filename
    klasse_name = report_data['klasse']['name'].replace(' ', '_')
    timestamp = datetime.now().strftime('%Y%m%d')
    filename = f"klassenbericht_{klasse_name}_{timestamp}.pdf"

    return Response(
        pdf_buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/admin/klasse/<int:klasse_id>/schueler-hinzufuegen', methods=['POST'])
@admin_required
def admin_klasse_schueler_hinzufuegen(klasse_id):
    batch_input = request.form['batch_input']
    existing_usernames = models.get_existing_usernames()
    existing_netzwerk_ids = models.get_existing_netzwerk_ids()

    # Collect created students for PDF
    created_students = []

    for line in batch_input.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) >= 2:
            nachname = parts[0].strip()
            vorname = parts[1].strip()

            username = generate_username(existing_usernames, vorname, nachname)
            existing_usernames.add(username)
            password = generate_password()
            netzwerk_id = models.generate_netzwerk_id(nachname, vorname, existing_netzwerk_ids)
            existing_netzwerk_ids.add(netzwerk_id)

            student_id = models.create_student(nachname, vorname, username, password, netzwerk_id=netzwerk_id)
            models.add_student_to_klasse(student_id, klasse_id)

            # Store for PDF generation
            created_students.append({
                'nachname': nachname,
                'vorname': vorname,
                'username': username,
                'password': password
            })

    if not created_students:
        flash('Keine Schüler hinzugefügt.', 'warning')
        return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))

    # Generate PDF with credentials
    klasse = models.get_klasse(klasse_id)
    pdf_buffer = generate_credentials_pdf(created_students, klasse['name'])

    # Return PDF as download
    return Response(
        pdf_buffer.getvalue(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename=zugangsdaten_{klasse["name"]}.pdf'
        }
    )


@app.route('/admin/klasse/<int:klasse_id>/thema-zuweisen', methods=['POST'])
@admin_required
def admin_klasse_thema_zuweisen(klasse_id):
    task_id = request.form['task_id']
    if task_id:
        models.assign_task_to_klasse(klasse_id, int(task_id))
        flash('Thema zugewiesen. ✅', 'success')

    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/sidequest-zuweisen', methods=['POST'])
@admin_required
def admin_klasse_sidequest_zuweisen(klasse_id):
    task_id = request.form.get('task_id')
    student_ids = request.form.getlist('student_ids')
    if task_id and student_ids:
        for sid in student_ids:
            models.assign_task_to_student(int(sid), klasse_id, int(task_id), rolle='sidequest')
        flash(f'Freiwilliges Thema für {len(student_ids)} Schüler zugewiesen. ✅', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/ueben-freischalten', methods=['POST'])
@admin_required
def admin_klasse_ueben_freischalten(klasse_id):
    task_id = request.form.get('task_id')
    action = request.form.get('action', 'unlock')
    if task_id:
        unlocked = action == 'unlock'
        models.set_practice_unlock_for_class(klasse_id, int(task_id), unlocked)
        msg = 'Fragen freigeschaltet. ✅' if unlocked else 'Freischaltung aufgehoben.'
        flash(msg, 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/lernpfad-setzen', methods=['POST'])
@admin_required
def admin_klasse_lernpfad(klasse_id):
    lernpfad = request.form.get('lernpfad')
    if lernpfad not in ('wanderweg', 'bergweg', 'gipfeltour', 'seilbahn'):
        flash('Ungültiger Lernpfad.', 'danger')
        return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))
    models.set_class_lernpfad(klasse_id, lernpfad)
    flash(f'Lernpfad für alle Schüler gesetzt. ✅', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/themen-reihenfolge', methods=['GET', 'POST'])
@admin_required
def admin_topic_queue(klasse_id):
    """Manage topic queue (ordered progression) for a class."""
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))

    if request.method == 'POST':
        task_ids = request.form.getlist('task_ids', type=int)
        models.set_topic_queue(klasse_id, task_ids)
        flash('Themen-Reihenfolge gespeichert. ✅', 'success')
        return redirect(url_for('admin_topic_queue', klasse_id=klasse_id))

    queue = models.get_topic_queue(klasse_id)
    queued_ids = {q['task_id'] for q in queue}
    all_tasks = models.get_all_tasks()
    available_tasks = [t for t in all_tasks if t['id'] not in queued_ids]
    themen_exact, themen_other = split_tasks_by_stufe(available_tasks, [klasse.get('klassenstufe')])

    return render_template('admin/topic_queue.html',
                           klasse=klasse, queue=queue,
                           themen_exact=themen_exact, themen_other=themen_other)


# ============ Admin: Schüler ============

@app.route('/admin/schueler/<int:student_id>')
@admin_required
def admin_schueler_detail(student_id):
    student = models.get_student(student_id)
    if not student:
        flash('Schüler nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    klassen = models.get_student_klassen(student_id)
    all_klassen = models.get_all_klassen()
    tasks = models.get_all_tasks()

    # Get current tasks for each class
    student_tasks = {}
    for klasse in klassen:
        student_tasks[klasse['id']] = models.get_student_task(student_id, klasse['id'])

    artifact_feedback = models.get_all_artifact_feedback_for_student(student_id)
    artifact_files = models.get_all_student_artifact_files_for_student(student_id)
    data_summary = models.get_student_data_summary(student_id)
    fork_choices = models.get_student_fork_choices(student_id)

    # The topic dropdown is not tied to one class, so match against every
    # grade level this student sits in.
    themen_exact, themen_other = split_tasks_by_stufe(
        tasks, [k.get('klassenstufe') for k in klassen])

    return render_template('admin/schueler_detail.html',
                           student=student,
                           klassen=klassen,
                           all_klassen=all_klassen,
                           tasks=tasks,
                           themen_exact=themen_exact,
                           themen_other=themen_other,
                           student_tasks=student_tasks,
                           artifact_feedback=artifact_feedback,
                           artifact_files=artifact_files,
                           data_summary=data_summary,
                           fork_choices=fork_choices)


@app.route('/admin/schueler/<int:student_id>/loeschen', methods=['POST'])
@admin_required
def admin_schueler_loeschen(student_id):
    _unlink_artifact_files(models.delete_student(student_id))
    flash('Schüler gelöscht.', 'success')
    return redirect(request.referrer or url_for('admin_klassen'))


@app.route('/admin/schueler/<int:student_id>/datenauszug')
@admin_required
def admin_schueler_datenauszug(student_id):
    student = models.get_student(student_id)
    if not student:
        flash('Schüler nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    data = models.get_student_data_export(student_id)
    filename = f"datenauszug-{student['username']}.json"
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/admin/schueler/<int:student_id>/passwort-reset', methods=['POST'])
@admin_required
def admin_schueler_passwort_reset(student_id):
    student = models.get_student(student_id)
    if not student:
        flash('Schüler nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))

    # Generate new password
    new_password = generate_password()
    models.reset_student_password(student_id, new_password)

    flash(f'Neues Passwort für {student["vorname"]}: {new_password}', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/lernpfad', methods=['POST'])
@admin_required
def admin_schueler_lernpfad(student_id):
    lernpfad = request.form.get('lernpfad')
    if lernpfad not in ('wanderweg', 'bergweg', 'gipfeltour', 'seilbahn'):
        flash('Ungültiger Lernpfad.', 'danger')
        return redirect(url_for('admin_schueler_detail', student_id=student_id))
    models.update_student_setting(student_id, 'lernpfad', lernpfad)
    flash('Lernpfad gespeichert. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/fork-zweig', methods=['POST'])
@admin_required
def admin_schueler_fork_zweig(student_id):
    """Teacher reassignment of a student's fork/choice branch pick.

    Bypasses the student-side lock (is_fork_choice_locked) -- this is the
    override mechanism for the branch-imbalance risk noted in the design doc
    (docs/shared/lernmanager/fork-choice-artifact-model.md decision 1).
    """
    fork_group = request.form.get('fork_group')
    branch = request.form.get('branch')
    task_id = request.form.get('task_id', type=int)
    valid_branches = models.get_fork_branches(task_id, fork_group) if task_id and fork_group else set()
    if not fork_group or branch not in valid_branches:
        flash('Ungültige Zweig-Wahl.', 'danger')
        return redirect(url_for('admin_schueler_detail', student_id=student_id))
    models.set_student_fork_choice(student_id, fork_group, branch)
    flash('Zweig-Wahl aktualisiert. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/verschieben', methods=['POST'])
@admin_required
def admin_schueler_verschieben(student_id):
    from_klasse = request.form['from_klasse']
    to_klasse = request.form['to_klasse']
    if from_klasse and to_klasse:
        models.move_student_to_klasse(student_id, int(from_klasse), int(to_klasse))
        flash('Schüler verschoben. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/thema-zuweisen', methods=['POST'])
@admin_required
def admin_schueler_thema_zuweisen(student_id):
    klasse_id = request.form['klasse_id']
    task_id = request.form['task_id']
    if klasse_id and task_id:
        rolle = request.form.get('rolle', 'primary')
        models.assign_task_to_student(student_id, int(klasse_id), int(task_id), rolle)
        flash('Thema zugewiesen. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))



@app.route('/admin/schueler/<int:student_id>/klasse/<int:klasse_id>/abschliessen', methods=['POST'])
@admin_required
def admin_schueler_thema_abschliessen(student_id, klasse_id):
    student_task = models.get_student_task(student_id, klasse_id)
    if student_task:
        models.mark_task_complete(student_task['id'], manual=True)
        flash('Thema manuell abgeschlossen. ✅', 'success')
    return redirect(request.referrer or url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/bericht')
@admin_required
def admin_schueler_bericht(student_id):
    """Generate and download student progress report PDF (admin version)."""
    report_type = request.args.get('type', 'summary')  # 'summary' or 'complete'
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    # Validate report type
    if report_type not in ['summary', 'complete']:
        report_type = 'summary'

    # Get report data
    report_data = models.get_report_data_for_student(
        student_id,
        report_type=report_type,
        date_from=date_from,
        date_to=date_to
    )

    if not report_data:
        flash('Schüler nicht gefunden.', 'error')
        return redirect(url_for('admin_dashboard'))

    # Generate PDF
    pdf_buffer = generate_student_report_pdf(report_data, report_type=report_type)

    # Prepare filename
    student = report_data['student']
    student_name = f"{student['nachname']}_{student['vorname']}".replace(' ', '_')
    timestamp = datetime.now().strftime('%Y%m%d')
    report_label = 'vollstaendig' if report_type == 'complete' else 'zusammenfassung'
    filename = f"fortschrittsbericht_{student_name}_{report_label}_{timestamp}.pdf"

    return Response(
        pdf_buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ============ Admin: Tasks ============

@app.route('/admin/themen')
@admin_required
def admin_themen():
    tasks = models.get_all_tasks()
    # Re-sort in Python: SQL orders `stufe` as text, so '10' would sort before '5'.
    tasks.sort(key=lambda t: (t['fach'] or '', stufe_sort_key(t['stufe']),
                              t['number'] or 0, t['name'] or ''))
    for task in tasks:
        task['stufe_key'] = stufe_sort_key(task['stufe'])[0]

    # Filter options come from what actually exists, so legacy values stay usable.
    faecher = sorted({t['fach'] for t in tasks if t['fach']})
    stufen = sorted({t['stufe'] for t in tasks if t['stufe']}, key=stufe_sort_key)

    return render_template('admin/themen.html', tasks=tasks, faecher=faecher, stufen=stufen)


@app.route('/admin/themen/export')
@admin_required
def admin_themen_export():
    tasks = models.export_all_tasks()
    data = {
        'version': '1.0',
        'exported_at': datetime.now().isoformat(),
        'tasks': tasks
    }
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=themen_export.json'}
    )


@app.route('/admin/thema/<int:task_id>/drucken')
@admin_required
def admin_thema_drucken(task_id):
    task = models.get_task(task_id)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('admin_themen'))
    subtasks = [s for s in models.get_subtasks(task_id) if not s.get('hidden')]
    for sub in subtasks:
        sub['materials'] = models.get_materials_for_subtask(task_id, sub['id'])
    return render_template('student/print_tasks.html', task=task, subtasks=subtasks, single=False)


@app.route('/admin/thema/<int:task_id>/export')
@admin_required
def admin_thema_export(task_id):
    task_data = models.export_task_to_dict(task_id)
    if not task_data:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('admin_themen'))
    data = {
        'version': '1.0',
        'exported_at': datetime.now().isoformat(),
        'task': task_data
    }
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename=thema_{task_id}_export.json'}
    )


@app.route('/admin/thema/<int:task_id>/export-zip')
@admin_required
def admin_thema_export_zip(task_id):
    task_data = models.export_task_to_dict(task_id)
    if not task_data:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('admin_themen'))

    export = {
        'version': '1.0',
        'exported_at': datetime.now().isoformat(),
        'task': task_data
    }
    json_bytes = json.dumps(export, ensure_ascii=False, indent=2).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('task.json', json_bytes)
        for mat in task_data.get('materials', []):
            if mat['typ'] == 'datei':
                filepath = os.path.join(config.UPLOAD_FOLDER, mat['pfad'])
                if os.path.isfile(filepath):
                    # Storage is namespaced per topic, the ZIP is not: entries are
                    # bare filenames, so a re-import lands them in its own folder.
                    zf.write(filepath, material_filename(mat['pfad']))

    buf.seek(0)
    safe_name = slugify(task_data['name'])
    timestamp = datetime.now().strftime('%Y%m%d')
    return Response(
        buf.read(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename=thema_{safe_name}_{timestamp}.zip'}
    )


import tempfile as _tempfile
_IMPORT_TMP_DIR = os.path.join(_tempfile.gettempdir(), 'lernmanager_import')


def _save_import_zip(file_bytes):
    """Save uploaded ZIP bytes to a temp file. Returns tmp_id string."""
    os.makedirs(_IMPORT_TMP_DIR, exist_ok=True)
    now = datetime.now().timestamp()
    for fname in os.listdir(_IMPORT_TMP_DIR):
        fpath = os.path.join(_IMPORT_TMP_DIR, fname)
        if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 7200:
            try:
                os.remove(fpath)
            except OSError:
                pass
    tmp_id = uuid.uuid4().hex
    with open(os.path.join(_IMPORT_TMP_DIR, f'{tmp_id}.zip'), 'wb') as f:
        f.write(file_bytes)
    return tmp_id


def _extract_import_zip_files(tmp_id, imported_targets):
    """Extract material files from temp ZIP to UPLOAD_FOLDER. Always removes temp.

    imported_targets is a list of (task_id, task_dict) for the topics that were
    actually created or overwritten -- a topic whose import failed gets no files.
    ZIP entries are bare filenames; on disk each topic's files go in its own
    folder, so two topics may ship the same filename without clobbering.
    Returns the list of extracted filenames (bare, as the teacher named them).
    """
    if not tmp_id:
        return []
    tmp_path = os.path.join(_IMPORT_TMP_DIR, f'{tmp_id}.zip')
    if not os.path.isfile(tmp_path):
        return []
    extracted = []
    try:
        with zipfile.ZipFile(tmp_path) as zf:
            zip_names = set(zf.namelist())
            os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
            upload_dir = os.path.abspath(config.UPLOAD_FOLDER)
            for task_id, task_data in imported_targets:
                unit_slug = (models.get_task(task_id) or {}).get('unit_slug')
                for mat in task_data.get('materials', []):
                    if mat.get('typ') == 'datei' and mat.get('pfad') in zip_names:
                        # Second line of defence behind validate_task_structure:
                        # nothing reaches UPLOAD_FOLDER that download_material
                        # would not serve safely.
                        if not allowed_file(mat['pfad']):
                            continue
                        pfad = material_pfad(task_id, mat['pfad'], unit_slug)
                        if not pfad:
                            continue
                        dest = os.path.abspath(os.path.join(upload_dir, pfad))
                        # Zip entry names aren't restricted by the format -- a crafted
                        # '../../etc/...' pfad would otherwise write outside upload_dir.
                        # material_pfad already reduces it to a basename; this is the belt.
                        if os.path.commonpath([upload_dir, dest]) != upload_dir:
                            continue
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with zf.open(mat['pfad']) as src, open(dest, 'wb') as dst:
                            dst.write(src.read())
                        extracted.append(mat['pfad'])
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return extracted


def _build_topic_preview(task_data, bundled_files=None):
    """Build a preview dict for one topic from import JSON."""
    task = task_data['task']
    subtasks = task.get('subtasks', [])
    path_counts = {'wanderweg': 0, 'bergweg': 0, 'gipfeltour': 0, 'seilbahn': 0}
    for s in subtasks:
        p = s.get('path', 'bergweg')
        if p in path_counts:
            path_counts[p] += 1
    existing_id = check_duplicate(task_data)
    file_mat_count = sum(1 for m in task.get('materials', []) if m.get('typ') == 'datei')
    return {
        'name': task['name'],
        'fach': task['fach'],
        'stufe': task['stufe'],
        'kategorie': task.get('kategorie', 'pflicht'),
        'number': task.get('number'),
        'subtask_count': len(subtasks),
        'path_counts': path_counts,
        'material_count': len(task.get('materials', [])),
        'file_material_count': file_mat_count,
        'bundled_files': bundled_files,
        'topic_quiz_count': len(task['quiz']['questions']) if task.get('quiz') else 0,
        'subtask_quiz_count': sum(1 for s in subtasks if s.get('quiz')),
        'is_duplicate': existing_id is not None,
        'existing_task_id': existing_id,
    }


@app.route('/admin/themen/import', methods=['GET', 'POST'])
@admin_required
def admin_themen_import():
    if request.method == 'GET':
        return render_template('admin/themen_import.html', preview=False)

    action = request.form.get('action')

    # --- Preview phase: parse uploaded file ---
    if action == 'preview':
        file = request.files.get('json_file')
        fname = file.filename if file else ''
        if not file or not (fname.endswith('.json') or fname.endswith('.zip')):
            flash('Bitte eine JSON- oder ZIP-Datei auswählen.', 'danger')
            return render_template('admin/themen_import.html', preview=False)

        file_bytes = file.read()
        zip_tmp_id = None
        bundled_filenames = None

        if fname.endswith('.zip'):
            try:
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                    names = zf.namelist()
                    json_entry = 'task.json' if 'task.json' in names else ('thema.json' if 'thema.json' in names else None)
                    if not json_entry:
                        return render_template('admin/themen_import.html', preview=True,
                                               errors=["ZIP enthält keine 'task.json'."])
                    raw = zf.read(json_entry).decode('utf-8')
                    data = json.loads(raw)
                    bundled_filenames = [n for n in names if n not in ('task.json', 'thema.json') and not n.endswith('/')]
            except zipfile.BadZipFile:
                return render_template('admin/themen_import.html', preview=True,
                                       errors=["Ungültige ZIP-Datei."])
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                return render_template('admin/themen_import.html', preview=True,
                                       errors=[f"Ungültiges JSON in task.json: {e}"])
        else:
            try:
                raw = file_bytes.decode('utf-8')
                data = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                return render_template('admin/themen_import.html', preview=True,
                                       errors=[f'Ungültiges JSON: {e}'])

        # Normalize to list of {"task": {...}} dicts
        task_list = []
        errors = []
        soft_warnings = []  # non-fatal issues (e.g. invalid artifact_gate)
        if 'tasks' in data and isinstance(data['tasks'], list):
            for t in data['tasks']:
                wrapped = {'task': t}
                try:
                    validate_task_structure(wrapped, warnings=soft_warnings)
                    task_list.append(wrapped)
                except ValidationError as e:
                    errors.append(f"{t.get('name', '?')}: {e}")
        elif 'task' in data:
            try:
                validate_task_structure(data, warnings=soft_warnings)
                task_list.append(data)
            except ValidationError as e:
                errors.append(str(e))
        else:
            errors.append("JSON muss 'task' oder 'tasks' als Wurzelelement enthalten.")

        # For ZIP: verify all required material files are bundled
        if bundled_filenames is not None and task_list and not errors:
            bundled_set = set(bundled_filenames)
            missing = [
                mat['pfad']
                for td in task_list
                for mat in td['task'].get('materials', [])
                if mat.get('typ') == 'datei' and mat.get('pfad') not in bundled_set
            ]
            if missing:
                errors.append(f"Fehlende Dateien im ZIP: {', '.join(missing)}")

            # Content has to match the name here too -- caught now, while the
            # admin is still looking at a preview, rather than as a silently
            # skipped file at extraction time.
            if not missing:
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                    for td in task_list:
                        for mat in td['task'].get('materials', []):
                            if mat.get('typ') != 'datei':
                                continue
                            ok, sniffed = content_matches_extension(
                                mat['pfad'], zf.read(mat['pfad'])
                            )
                            if not ok:
                                errors.append(
                                    f"'{mat['pfad']}' ist in Wirklichkeit eine "
                                    f"{sniffed.upper()}-Datei."
                                    if sniffed else
                                    f"'{mat['pfad']}' ist keine gültige Datei dieses Typs."
                                )

        if errors:
            return render_template('admin/themen_import.html', preview=True, errors=errors)

        if bundled_filenames is not None:
            zip_tmp_id = _save_import_zip(file_bytes)

        # Build preview for each topic
        topics_preview = [_build_topic_preview(td, bundled_files=bundled_filenames) for td in task_list]
        warnings = list(soft_warnings)  # start with gate/soft warnings from validation
        for tp in topics_preview:
            if tp['is_duplicate']:
                warnings.append(f"'{tp['name']}' ({tp['fach']} {tp['stufe']}) existiert bereits.")

        # Fetch all existing tasks for the overwrite dropdown
        existing_tasks = models.get_all_tasks()

        # Re-serialize the validated data for the hidden form field
        export_data = {'tasks': [td['task'] for td in task_list]}
        json_data = json.dumps(export_data, ensure_ascii=False)

        return render_template('admin/themen_import.html', preview=True,
                               topics_preview=topics_preview, warnings=warnings,
                               json_data=json_data, existing_tasks=existing_tasks,
                               zip_tmp_id=zip_tmp_id)

    # --- Confirm phase: actually import ---
    if action == 'confirm':
        raw = request.form.get('json_data', '')
        zip_tmp_id = request.form.get('zip_tmp_id', '')
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            _extract_import_zip_files(zip_tmp_id, [])  # clean up temp file
            flash('Ungültige Daten. Bitte erneut hochladen.', 'danger')
            return redirect(url_for('admin_themen_import'))

        imported = []
        overwritten = []
        overwritten_reset = []
        warnings = []
        # (task_id, task_dict) for topics that really landed -- the ZIP step below
        # writes each topic's files into that topic's own folder, so it needs the id.
        import_targets = []

        for i, task_entry in enumerate(data.get('tasks', [])):
            wrapped = {'task': task_entry}
            action_value = request.form.get(f'action_{i}', 'new')
            reset = request.form.get(f'reset_{i}') == '1'

            if action_value != 'new':
                # Overwrite existing topic
                try:
                    target_id = int(action_value)
                    w = []
                    overwrite_task_from_import(target_id, wrapped, reset_progress=reset, warnings=w)
                    warnings.extend(w)
                    import_targets.append((target_id, task_entry))
                    if reset:
                        overwritten_reset.append(task_entry['name'])
                    else:
                        overwritten.append(task_entry['name'])
                except (ValueError, Exception) as e:
                    warnings.append(f"Fehler beim Überschreiben von '{task_entry['name']}': {e}")
            else:
                # Import as new (existing behavior)
                w = []
                task_id = do_import_task(wrapped, warnings=w)
                warnings.extend(w)
                if task_id:
                    import_targets.append((task_id, task_entry))
                    imported.append(task_entry['name'])

        if imported:
            flash(f"{len(imported)} Thema{'en' if len(imported) > 1 else ''} importiert: {', '.join(imported)}", 'success')
        if overwritten:
            flash(f"{len(overwritten)} überschrieben: {', '.join(overwritten)}", 'success')
        if overwritten_reset:
            flash(f"{len(overwritten_reset)} überschrieben + Fortschritte zurückgesetzt: {', '.join(overwritten_reset)}", 'success')
        for w in warnings:
            flash(w, 'warning')

        if zip_tmp_id:
            expected_files = [
                mat['pfad']
                for _tid, t in import_targets
                for mat in t.get('materials', [])
                if mat.get('typ') == 'datei' and mat.get('pfad')
            ]
            tmp_path = os.path.join(_IMPORT_TMP_DIR, f'{zip_tmp_id}.zip')
            if not os.path.isfile(tmp_path):
                flash('ZIP-Datei nicht mehr verfügbar (Server-Neustart?). Bitte erneut als ZIP importieren, um die Dateien zu übertragen.', 'warning')
            else:
                extracted = _extract_import_zip_files(zip_tmp_id, import_targets)
                if extracted:
                    flash(f"{len(extracted)} Datei(en) importiert: {', '.join(extracted)}", 'success')
                not_extracted = [f for f in expected_files if f not in extracted]
                if not_extracted:
                    flash(f"Warnung: {len(not_extracted)} Datei(en) fehlen noch: {', '.join(not_extracted)}", 'warning')

        return redirect(url_for('admin_themen'))

    return redirect(url_for('admin_themen_import'))


@app.route('/admin/thema/neu', methods=['GET', 'POST'])
@admin_required
def admin_thema_neu():
    if request.method == 'POST':
        task_id = models.create_task(
            name=request.form['name'],
            beschreibung=request.form['beschreibung'],
            lernziel=request.form['lernziel'],
            fach=request.form['fach'],
            stufe=request.form['stufe'],
            kategorie=request.form['kategorie'],
            number=int(request.form.get('number', 0)),
            why_learn_this=request.form.get('why_learn_this') or None,
            lernziel_schueler=request.form.get('lernziel_schueler') or None,
            module_tier=request.form.get('module_tier', 'kern_standard'),
            unit_slug=request.form.get('unit_slug') or None
        )
        flash('Thema erstellt. ✅', 'success')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    return render_template('admin/thema_form.html', task=None, subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/thema/<int:task_id>')
@admin_required
def admin_thema_detail(task_id):
    task = models.get_task(task_id)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('admin_themen'))
    subtasks = models.get_subtasks(task_id)
    materials = models.get_materials(task_id)
    material_assignments = models.get_material_subtask_assignments(task_id)
    building_on_text, arriving_at_text = _connections_to_admin_fields(task.get('connections_json'))
    delete_impact = models.get_task_deletion_impact(task_id)
    return render_template('admin/thema_detail.html', task=task, subtasks=subtasks, materials=materials, subjects=config.SUBJECTS, levels=config.LEVELS, material_assignments=material_assignments, building_on_text=building_on_text, arriving_at_text=arriving_at_text, delete_impact=delete_impact)


@app.route('/admin/thema/<int:task_id>/bearbeiten', methods=['POST'])
@admin_required
def admin_thema_bearbeiten(task_id):
    try:
        quiz_json = validate_quiz_json(request.form.get('quiz_json'))
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    unit_slug = request.form.get('unit_slug') or None
    if unit_slug and not re.match(r'^[a-z0-9_]+$', unit_slug):
        flash("Unit-Slug ungültig. Nur Kleinbuchstaben, Ziffern und Unterstriche.", 'danger')
        return redirect(url_for('admin_thema_detail', task_id=task_id))
    if unit_slug:
        slug_owner = models.get_task_by_unit_slug(unit_slug)
        if slug_owner and slug_owner['id'] != task_id:
            flash(f"Unit-Slug '{unit_slug}' wird bereits von Thema '{slug_owner['name']}' verwendet.", 'danger')
            return redirect(url_for('admin_thema_detail', task_id=task_id))

    connections = _parse_connections_form(request.form.get('building_on'), request.form.get('arriving_at'))
    connections_json = json.dumps(connections, ensure_ascii=False) if connections else None

    models.update_task(
        task_id=task_id,
        name=request.form['name'],
        beschreibung=request.form['beschreibung'],
        lernziel=request.form['lernziel'],
        fach=request.form['fach'],
        stufe=request.form['stufe'],
        kategorie=request.form['kategorie'],
        quiz_json=quiz_json,
        number=int(request.form.get('number', 0)),
        why_learn_this=request.form.get('why_learn_this') or None,
        subtask_quiz_required=1 if request.form.get('subtask_quiz_required') else 0,
        lernziel_schueler=request.form.get('lernziel_schueler') or None,
        module_tier=request.form.get('module_tier', 'kern_standard'),
        unit_slug=unit_slug,
        connections_json=connections_json
    )
    flash('Thema aktualisiert. ✅', 'success')
    return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/admin/thema/<int:task_id>/loeschen', methods=['POST'])
@admin_required
def admin_thema_loeschen(task_id):
    import sqlite3
    impact = models.get_task_deletion_impact(task_id)
    try:
        artifact_disk_filenames, material_pfade = models.delete_task(task_id)
        _unlink_artifact_files(artifact_disk_filenames)
        _unlink_material_files(material_pfade)
        removed = []
        if impact['artifact_files']:
            removed.append(f"{impact['artifact_files']} Abgabe(n)")
        if impact['grading_results']:
            removed.append(f"{impact['grading_results']} Bewertung(en)")
        detail = f" Mitgelöscht: {', '.join(removed)}." if removed else ''
        flash(f'Thema gelöscht.{detail}', 'success')
    except sqlite3.IntegrityError as exc:
        # Every known FK into task/subtask is cleared by delete_task(); if this
        # still fires, a new table gained a non-cascading reference.
        app.logger.exception('delete_task(%s) hit an unhandled FK constraint', task_id)
        flash(f'Thema konnte nicht gelöscht werden — nicht behandelte Verknüpfung: {exc}', 'danger')
    return redirect(url_for('admin_themen'))


@app.route('/admin/thema/<int:task_id>/aufgaben', methods=['GET', 'POST'])
@admin_required
def admin_thema_aufgaben(task_id):
    if request.method == 'GET':
        # API endpoint: return subtasks as JSON
        subtasks = models.get_subtasks(task_id)
        return jsonify(subtasks)
    else:
        # POST: update subtasks (includes time estimates, per-subtask quizzes, path fields)
        subtasks_list = request.form.getlist('subtasks[]')
        estimated_minutes_list = request.form.getlist('estimated_minutes[]')
        quiz_json_list = request.form.getlist('quiz_json[]')
        path_list = request.form.getlist('path[]')
        path_model_list = request.form.getlist('path_model[]')
        fertig_wenn_list = request.form.getlist('fertig_wenn[]')
        tipps_list = request.form.getlist('tipps[]')
        checkpoint_type_list = request.form.getlist('checkpoint_type[]')
        kern_standard_tag_list = request.form.getlist('kern_standard_tag[]')
        checkpoint_hints_list = request.form.getlist('checkpoint_hints[]')
        school_only_list = request.form.getlist('school_only[]')
        fork_group_list = request.form.getlist('fork_group[]')
        fork_branch_list = request.form.getlist('fork_branch[]')
        fork_branch_label_list = request.form.getlist('fork_branch_label[]')
        fork_branch_note_list = request.form.getlist('fork_branch_note[]')
        fork_required_list = request.form.getlist('fork_required[]')

        # A subtask needs both fork_group and fork_branch, or neither.
        for i, (fg, fb) in enumerate(zip(fork_group_list, fork_branch_list)):
            if bool(fg.strip()) != bool(fb.strip()):
                flash(f'Aufgabe {i+1}: Fork-Gruppe und Zweig müssen beide oder keins ausgefüllt sein.', 'danger')
                return redirect(url_for('admin_thema_detail', task_id=task_id))

        # Validate all subtask quiz JSONs before saving
        for i, qj in enumerate(quiz_json_list):
            try:
                validated = validate_quiz_json(qj)
            except ValueError as e:
                flash(f'Aufgabe {i+1} Quiz-JSON: {e}', 'danger')
                return redirect(url_for('admin_thema_detail', task_id=task_id))
            # Quiz-checkpoints render as radio-button retry sessions (single-select
            # only) - a multi-correct MC question there could never be answered right.
            is_checkpoint_quiz = i < len(checkpoint_type_list) and checkpoint_type_list[i] == 'quiz'
            if validated and is_checkpoint_quiz:
                for qi, question in enumerate(json.loads(validated).get('questions', [])):
                    if question.get('type', 'multiple_choice') == 'multiple_choice' and len(question.get('correct', [])) != 1:
                        flash(f'Aufgabe {i+1}, Frage {qi+1}: Quiz-Checkpoints brauchen genau eine richtige Antwort.', 'danger')
                        return redirect(url_for('admin_thema_detail', task_id=task_id))

        models.update_subtasks(task_id, subtasks_list, estimated_minutes_list, quiz_json_list,
                               path_list=path_list, path_model_list=path_model_list,
                               fertig_wenn_list=fertig_wenn_list, tipps_list=tipps_list,
                               checkpoint_type_list=checkpoint_type_list,
                               kern_standard_tag_list=kern_standard_tag_list,
                               checkpoint_hints_list=checkpoint_hints_list,
                               school_only_list=school_only_list,
                               fork_group_list=fork_group_list, fork_branch_list=fork_branch_list,
                               fork_branch_label_list=fork_branch_label_list,
                               fork_branch_note_list=fork_branch_note_list,
                               fork_required_list=fork_required_list)
        flash('Aufgaben aktualisiert.', 'success')
        return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/admin/thema/<int:task_id>/material-link', methods=['POST'])
@admin_required
def admin_thema_material_link(task_id):
    url = request.form['url'].strip()
    beschreibung = request.form.get('beschreibung', '').strip()
    attribution = request.form.get('attribution', '').strip() or None
    if url:
        models.create_material(task_id, 'link', url, beschreibung, attribution)
        flash('Link hinzugefügt. ✅', 'success')
    return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/admin/thema/<int:task_id>/material-upload', methods=['POST'])
@admin_required
def admin_thema_material_upload(task_id):
    if 'file' not in request.files:
        flash('Keine Datei ausgewählt.', 'warning')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    file = request.files['file']
    if file.filename == '':
        flash('Keine Datei ausgewählt.', 'warning')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    if not (file and allowed_file(file.filename)):
        flash(f"Ungültiger Dateityp. Erlaubt: "
              f"{', '.join(sorted(e.upper() for e in config.ALLOWED_EXTENSIONS))}", 'danger')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    # The extension says what we may store and how we serve it; the content has
    # to agree, or renaming a file is enough to pick a serving rule meant for
    # something else.
    file_bytes = file.read()
    ok, sniffed = content_matches_extension(file.filename, file_bytes)
    if not ok:
        was_ist_es = (f"ist eine {sniffed.upper()}-Datei"
                      if sniffed else "ist keine gültige Datei dieses Typs")
        flash(f"Der Inhalt passt nicht zur Dateiendung: „{file.filename}“ "
              f"{was_ist_es}. Bitte mit der richtigen Endung speichern und "
              f"erneut hochladen.", 'danger')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    try:
        # Ensure upload directory exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        filename = secure_filename(file.filename)
        # Same rule as the ZIP importer: the file lives in this topic's folder,
        # so its name only has to be unique within the topic (was a "<id>_" prefix).
        pfad = material_pfad(task_id, filename, (models.get_task(task_id) or {}).get('unit_slug'))
        if not pfad:
            flash('Ungültiger Dateiname.', 'danger')
            return redirect(url_for('admin_thema_detail', task_id=task_id))
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], pfad)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # Save the file (already read into memory for the content check above)
        with open(filepath, 'wb') as out:
            out.write(file_bytes)

        # Verify file was saved
        if not os.path.exists(filepath):
            raise IOError('Datei wurde nicht gespeichert.')

        # Add to database
        beschreibung = request.form.get('beschreibung', '').strip()
        attribution = request.form.get('attribution', '').strip() or None
        school_only = 'school_only' in request.form
        models.create_material(task_id, 'datei', pfad, beschreibung, attribution, school_only)

        flash('Datei hochgeladen. ✅', 'success')

    except PermissionError as e:
        app.logger.error(f'Upload permission error: {e}')
        flash('Fehler: Keine Berechtigung zum Speichern der Datei. Bitte Administrator kontaktieren.', 'danger')
    except OSError as e:
        app.logger.error(f'Upload OS error: {e}')
        if 'No space left' in str(e):
            flash('Fehler: Kein Speicherplatz verfügbar.', 'danger')
        else:
            flash('Fehler: Datei konnte nicht gespeichert werden.', 'danger')
    except Exception as e:
        app.logger.error(f'Upload error: {e}')
        flash('Fehler beim Hochladen der Datei. Bitte erneut versuchen.', 'danger')
        # Clean up partially uploaded file if it exists
        if 'filepath' in locals() and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

    return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/admin/material/<int:material_id>/loeschen', methods=['POST'])
@admin_required
def admin_material_loeschen(material_id):
    try:
        # Get material info before deleting from database
        material = models.get_material(material_id)

        # Delete from database
        models.delete_material(material_id)

        # If it's a file (not a link), try to delete the physical file
        if material and material['typ'] == 'datei':
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], material['pfad'])
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    app.logger.warning(f'Could not delete file {filepath}: {e}')
                    # Don't fail the whole operation if file deletion fails

        flash('Material gelöscht.', 'success')
    except Exception as e:
        app.logger.error(f'Error deleting material: {e}')
        flash('Fehler beim Löschen des Materials.', 'danger')

    return redirect(request.referrer or url_for('admin_themen'))


@app.route('/admin/material/<int:material_id>/umbenennen', methods=['POST'])
@admin_required
def admin_material_umbenennen(material_id):
    data = request.get_json()
    beschreibung = (data.get('beschreibung') or '').strip()
    if not beschreibung:
        return jsonify({'error': 'Name darf nicht leer sein.'}), 400
    models.update_material_beschreibung(material_id, beschreibung)
    return jsonify({'ok': True})


@app.route('/admin/material/<int:material_id>/schulnetz', methods=['POST'])
@admin_required
def admin_material_schulnetz(material_id):
    material = models.get_material(material_id)
    if not material or material['typ'] != 'datei':
        return jsonify({'error': 'Nur Dateien können auf Schulnetzwerk beschränkt werden.'}), 400
    data = request.get_json()
    models.update_material_school_only(material_id, bool(data.get('school_only')))
    return jsonify({'ok': True})


@app.route('/admin/thema/<int:task_id>/material-zuordnung', methods=['POST'])
@admin_required
def admin_material_zuordnung(task_id):
    """Save material-to-Aufgabe assignments from checkbox table."""
    subtasks = models.get_subtasks(task_id)
    materials = models.get_materials(task_id)
    subtask_ids = [s['id'] for s in subtasks]

    for material in materials:
        mid = material['id']
        # Collect checked subtask IDs for this material
        checked = request.form.getlist(f'mat_{mid}[]')
        checked_ids = [int(x) for x in checked if x]

        # If all subtasks are checked (or "alle" is checked), clear assignments
        alle_checked = request.form.get(f'mat_{mid}_alle')
        if alle_checked or set(checked_ids) == set(subtask_ids):
            models.set_material_subtask_assignments(mid, [])
        else:
            models.set_material_subtask_assignments(mid, checked_ids)

    flash('Material-Zuordnung gespeichert. ✅', 'success')
    return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/material/<int:material_id>/download')
def download_material(material_id):
    """Authenticated file download - requires login as admin or student."""
    # Check if user is logged in (admin or student)
    if 'admin_id' not in session and 'student_id' not in session:
        flash('Bitte melden Sie sich an.', 'warning')
        return redirect(url_for('login'))

    material = models.get_material(material_id)
    if not material:
        abort(404)

    # Only serve files, not links
    if material['typ'] != 'datei':
        abort(404)

    # School-network-only materials (e.g. Lehrbuch scans): gate by IP range
    if material['school_only']:
        ip_ranges = models.get_setting('network_gate_ip_ranges', '')
        if not is_ip_allowed(_get_client_ip(), ip_ranges):
            abort(403)

    # Verify file exists before serving
    filepath = os.path.join(config.UPLOAD_FOLDER, material['pfad'])
    if not os.path.exists(filepath):
        app.logger.error(f'File not found: {filepath}')
        flash('Datei nicht gefunden.', 'danger')
        abort(404)

    try:
        # Log file download
        user_id = session.get('admin_id') or session.get('student_id')
        user_type = 'admin' if 'admin_id' in session else 'student'
        models.log_analytics_event(
            event_type='file_download',
            user_id=user_id,
            user_type=user_type,
            metadata={
                'material_id': material_id,
                'filename': material_filename(material['pfad']),
                'typ': material['typ']
            }
        )

        # Only formats a browser is meant to display are served inline. Anything
        # else is handed over as a download, so a file type we never render
        # cannot become a page on our own origin. The whitelist decides what may
        # be stored; this decides what may be *shown* -- two different questions.
        inline = file_extension(material['pfad']) in config.INLINE_EXTENSIONS

        # In production, let nginx serve the file directly (X-Accel-Redirect)
        # This frees the Python thread immediately instead of streaming bytes
        if not app.debug and request.headers.get('X-Forwarded-For'):
            import mimetypes
            content_type = mimetypes.guess_type(material['pfad'])[0] or 'application/octet-stream'
            response = Response('')
            response.headers['X-Accel-Redirect'] = f'/protected-files/{material["pfad"]}'
            response.headers['Content-Type'] = content_type
            if not inline:
                # The stored pfad carries the topic folder; the student gets the
                # plain filename, not "kl6_startklar/01_Vorlage.docx".
                response.headers['Content-Disposition'] = (
                    f'attachment; filename="{material_filename(material["pfad"])}"'
                )
            return response

        # Development fallback: serve directly through Flask
        return send_from_directory(
            config.UPLOAD_FOLDER,
            material['pfad'],
            as_attachment=not inline
        )
    except PermissionError as e:
        app.logger.error(f'Download permission error: {e}')
        flash('Fehler: Keine Berechtigung zum Lesen der Datei.', 'danger')
        abort(403)
    except Exception as e:
        app.logger.error(f'Download error: {e}')
        flash('Fehler beim Laden der Datei.', 'danger')
        abort(500)


# ============ Admin: Password Change ============

@app.route('/admin/passwort', methods=['GET', 'POST'])
@admin_required
def admin_passwort():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Verify current password
        admin = models.verify_admin(session['admin_username'], current_password)
        if not admin:
            flash('Aktuelles Passwort ist falsch.', 'danger')
            return redirect(url_for('admin_passwort'))

        # Validate new password
        if len(new_password) < 6:
            flash('Das neue Passwort muss mindestens 6 Zeichen lang sein.', 'danger')
            return redirect(url_for('admin_passwort'))

        if new_password != confirm_password:
            flash('Die neuen Passwörter stimmen nicht überein.', 'danger')
            return redirect(url_for('admin_passwort'))

        # Update password
        models.update_admin_password(session['admin_id'], new_password)
        flash('Passwort erfolgreich geändert.', 'success')
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/passwort.html')


# ============ Admin: Quiz Answer Review ============

@app.route('/admin/quiz-antworten')
@admin_required
def admin_quiz_antworten():
    """Review text-based quiz answers (fill_blank, short_answer)."""
    filter_mode = request.args.get('filter', 'review')
    klasse_id = request.args.get('klasse_id', type=int)
    only_fallback = (filter_mode == 'review')

    answers = models.get_text_quiz_answers(klasse_id=klasse_id, only_fallback=only_fallback)
    klassen = models.get_all_klassen()

    return render_template('admin/quiz_antworten.html',
                         answers=answers,
                         klassen=klassen,
                         filter_mode=filter_mode,
                         klasse_id=klasse_id)


# ============ Admin: Checkpoint Review (Chemie Punktekonto) ============
#
# Reads what checkpoint_answer/checkpoint_attempt logged (migrate_047) and lets a
# teacher act on it (migrate_048). Two separate acts, deliberately not merged:
#   - override the session score  -> that IS the grade (checkpoint_attempt)
#   - judge a single answer       -> calibration data only (checkpoint_answer),
#                                    never touches any score
# See docs/shared/lernmanager/chemie-checkpoint-status.md and chemie's two schema
# gaps in todo.md.


# Double-click detection thresholds (see _is_duplicate_submission).
DUPLICATE_SUBMISSION_WINDOW_SECONDS = 15
DUPLICATE_SUBMISSION_SIMILARITY = 0.95


def _parse_log_timestamp(value):
    """SQLite CURRENT_TIMESTAMP -> datetime, or None if it is not the expected
    'YYYY-MM-DD HH:MM:SS' shape (rows written by an older path may differ)."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


def _answer_seconds_between(previous, current):
    """Seconds between two logged answers, or None if either timestamp is
    unreadable. Provided so duplicate detection can reason about time without
    re-doing timestamp parsing."""
    a = _parse_log_timestamp(previous.get('timestamp'))
    b = _parse_log_timestamp(current.get('timestamp'))
    if a is None or b is None:
        return None
    return abs((b - a).total_seconds())


def _normalized_answer_text(answer):
    """Answer text reduced for comparison: lowercased, collapsed whitespace.
    None for a give-up row (no text at all)."""
    text = answer.get('answer_text')
    if text is None:
        return None
    return ' '.join(str(text).lower().split())


def _is_duplicate_submission(previous, current):
    """True if `current` is an accidental re-submission of `previous` -- the same
    answer sent twice because the student clicked "Prüfen" again while the first
    request was still in flight -- rather than a genuine second attempt.

    Why this matters: a checkpoint question scores 3 only when attempts == 1
    (_checkpoint_question_scores). Before the busy-state guard existed
    (static/js/llm_button.js) the button stayed enabled during the LLM call, so a
    second click silently turned a 3 into a 2. Everything this flags is offered to
    the teacher as a suggested correction -- never applied automatically.

    Both arguments are checkpoint_answer rows (dicts), `previous` graded first.

    Rule (Patrick's call 2026-08-26):
      - within 15s of each other -- the server LLM budget is 5s, but a full class
        submitting at once can queue a response past 10s, and it is exactly those
        slow calls that make a student click again. A 5s window would miss them.
      - same verdict on both rows. A near-identical answer that *flips* wrong->correct
        ("Neutron" -> "Neutronen") is a genuine typo fix, not a resend -- this guard
        is what makes the fuzzy matching below safe.
        Note on how reliable that is: grading runs at temperature 0 (llm_grading.
        _call_llm), but greedy sampling is not a determinism guarantee -- on a
        batched fp8 endpoint the same input can occasionally be judged differently
        because batch composition changes floating-point reduction order. When that
        happens to a real double-click, the pair goes unflagged and the student
        simply keeps the score they already had. The failure mode is a missed
        repair, never a wrongly suggested grade change, which is the right way round
        for something a teacher has to confirm anyway.
      - text ~identical (>= 0.95 similarity after normalising). Exact equality would
        be enough for a true double-click; fuzzy is Patrick's call, on the reasoning
        that a second submission already caps the question at 2 points, so a
        generous flag costs at most one rejected suggestion.

    Deliberately NOT required: that the earlier answer was correct. Only correct-
    previous pairs move a score, but flagging the rest keeps the export honest about
    how often double-clicking happened at all (which is how we will tell whether the
    button fix worked).

    An unreadable timestamp means the time test cannot be made, so nothing is
    flagged -- a missing signal must not become a suggestion to change a grade.

    Returns: bool
    """
    if previous.get('gave_up') or current.get('gave_up'):
        return False

    seconds = _answer_seconds_between(previous, current)
    if seconds is None or seconds > DUPLICATE_SUBMISSION_WINDOW_SECONDS:
        return False

    if previous.get('correct') is None or current.get('correct') is None:
        return False
    if bool(previous['correct']) != bool(current['correct']):
        return False

    previous_text = _normalized_answer_text(previous)
    current_text = _normalized_answer_text(current)
    if not previous_text or not current_text:
        return False
    if previous_text == current_text:
        return True
    return difflib.SequenceMatcher(None, previous_text, current_text).ratio() >= \
        DUPLICATE_SUBMISSION_SIMILARITY


def _mc_option_label(option):
    """One multiple-choice option as plain text. Options are strings, or dicts when
    they carry an image (see CLAUDE.md § Quiz JSON format)."""
    if isinstance(option, dict):
        return option.get('text') or '(Bild)'
    return str(option)


def _mc_option_labels(question, indices):
    """Map stored option indices to their text, or None if that cannot be done.

    None means the caller falls back to showing the raw stored value. The snapshot
    can be older than the options (sessions predating quiz_snapshot_json) or a later
    content edit can have removed an option -- and a confidently wrong label is
    worse for a teacher checking a grade than an honest index.
    """
    options = question.get('options') if question else None
    if not options:
        return None
    try:
        labels = [_mc_option_labels_one(options, int(i)) for i in indices]
    except (TypeError, ValueError):
        return None
    if any(label is None for label in labels):
        return None
    return ' · '.join(labels)


def _mc_option_labels_one(options, index):
    return _mc_option_label(options[index]) if 0 <= index < len(options) else None


def _resolve_interactive_answer(question, answer_text):
    """Readable rendering of a logged ordering/matching answer.

    Stored as JSON (an array of item texts, or a {links: rechts} object). The raw
    JSON is legible in a way "[0]" never was, but "A → B → C" is what the teacher
    is actually comparing against the question. Returns None when unresolvable;
    the caller keeps the raw value.
    """
    try:
        submitted = json.loads(answer_text)
    except (TypeError, ValueError):
        return None
    return quiz_grading.answer_text(question, submitted) or None


def _resolve_mc_answer(question, answer_text):
    """The option text a student actually clicked, from the stored "[0]".

    MC answers are logged as a JSON list of indices (student_checkpoint_answer),
    which made the review UI show a bare "[0]" -- unreadable next to the question it
    answers. Returns None when unresolvable; the caller keeps the raw value.
    """
    try:
        indices = json.loads(answer_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(indices, list):
        return None
    return _mc_option_labels(question, indices)


def _checkpoint_question_review(answers, flagged_indices=frozenset()):
    """Group one session's logged answers by question and work out, per question:
    what was submitted, which submissions look like accidental duplicates, and what
    the score would be without them.

    Returns list of dicts (one per question_index, ascending):
        {'question_index', 'answers', 'duplicate_ids', 'flagged', 'scored',
         'scored_without_duplicates'}
    where 'scored'/'scored_without_duplicates' are the 0/2/3 values from
    _checkpoint_question_scores, so the two numbers are always derived by the same
    rule the student was graded under -- never a second copy of it. Both are None
    for a reported question: it carries no score until a teacher has ruled.

    flagged_indices: questions the student reported as broken. They are listed even
    when there is no answer to show -- a report costs nothing to make and needs no
    draft, so a question reported without one would otherwise vanish from the very
    view that exists to rule on it.
    """
    by_question = {}
    for answer in answers:
        by_question.setdefault(answer['question_index'], []).append(answer)
    for question_index in flagged_indices:
        by_question.setdefault(question_index, [])

    review = []
    for question_index in sorted(by_question):
        rows = sorted(by_question[question_index], key=lambda r: (r['attempt_no'], r['id']))
        flagged = question_index in flagged_indices

        duplicate_ids = set()
        # Compare each graded submission against the last one that wasn't itself
        # flagged -- otherwise a triple-click would only ever flag the second row.
        previous = None
        for row in rows:
            if row.get('gave_up'):
                continue
            if previous is not None and _is_duplicate_submission(previous, row):
                duplicate_ids.add(row['id'])
                continue
            previous = row

        def summarize(skip_ids):
            counted = [r for r in rows if r['id'] not in skip_ids and not r.get('gave_up')
                       and r.get('correct') is not None]
            return {
                # `solved` is read from ALL rows, never the filtered set: a duplicate
                # is by definition the same answer as one that is still counted, so
                # it can never be the only evidence the question was solved. Deriving
                # it from `counted` would mean a false-positive flag on a correct
                # attempt suggests 0 points instead of raising the score -- the one
                # direction in which a wrong flag could actually harm a student.
                'solved': any(r.get('correct') for r in rows if not r.get('gave_up')),
                'gave_up': any(r.get('gave_up') for r in rows),
                'flagged': flagged,
                'attempts': len(counted),
                'hints_used': max([r.get('hints_used_before') or 0 for r in rows], default=0),
            }

        scored = _checkpoint_question_scores([summarize(set())])[0]
        scored_clean = _checkpoint_question_scores([summarize(duplicate_ids)])[0]
        review.append({
            'question_index': question_index,
            'answers': rows,
            'duplicate_ids': duplicate_ids,
            'flagged': flagged,
            'scored': scored,
            'scored_without_duplicates': scored_clean,
        })
    return review


def _checkpoint_snapshot_questions(attempt):
    """Question list as it was when the checkpoint was answered.

    quiz_snapshot_json is the point of the snapshot (migrate_047): content can be
    edited afterwards, so reading today's quiz_json could show a different question
    than the student answered. Returns [] when there is no snapshot (rows written
    before migrate_047) -- the UI then shows the answers without question text.
    """
    raw = attempt.get('quiz_snapshot_json')
    if not raw:
        return []
    try:
        return json.loads(raw).get('questions', [])
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []


def _mark_calibration_relevance(answer, question_type):
    """Decide whether this answer is worth asking the teacher to calibrate.

    The verdict widget asks "War die KI-Bewertung richtig?", which is the wrong
    question for anything a model never touched: an MC answer is an index
    comparison ('mc'), a fill_blank that matched is a string comparison ('match'),
    an empty submit is neither ('empty'). No model, no prompt for a note to tune.
    Asking anyway cost the teacher a decision per answer and put rows with no KI
    verdict into the very disagreement data the field exists to collect.

    A fill_blank that did NOT match falls through to the LLM (_grade_warmup_answer),
    so it arrives here as 'llm' and is asked about -- the deterministic path only
    ever reports a match it is sure of.

    So the widget is offered when, and only when:
      - a model actually graded it (LLM_GRADERS), or
      - the deterministic path looks broken -- an MC answer whose stored indices no
        longer resolve against the options (Patrick's call 2026-08-28: ask only
        when something is obviously off), or
      - something is already recorded, so an existing verdict or note stays visible
        and clearable instead of being hidden by this rule.
    """
    answer['llm_graded'] = answer['grader'] in LLM_GRADERS
    answer['unresolved_choice'] = bool(
        question_type == 'multiple_choice'
        and not answer['gave_up']
        and answer['answer_text']
        and answer['answer_display'] is None
    )
    answer['show_verdict'] = bool(
        not answer['gave_up']
        and (answer['llm_graded']
             or answer['unresolved_choice']
             or answer.get('teacher_verdict') is not None
             or answer.get('teacher_note'))
    )


def _build_checkpoint_sessions(attempts):
    """Assemble the review UI's display model: each checkpoint session with its
    per-question answer log, duplicate flags and a suggested score."""
    answers_by_attempt = models.get_checkpoint_answers_for_attempts(
        [a['id'] for a in attempts]
    )
    flags_by_attempt = {}
    for flag in models.get_checkpoint_flags(attempt_ids=[a['id'] for a in attempts],
                                            limit=2000):
        flags_by_attempt.setdefault(flag['checkpoint_attempt_id'], {}) \
                        .setdefault(flag['question_index'], []).append(flag)
    # How many students reported each question, across the whole class -- the number
    # that says whether the question or the student is the problem.
    checkpoint_ids = {a['checkpoint_id'] for a in attempts}
    open_by_question = models.count_open_flags_by_question(checkpoint_ids)

    # Flags the teacher raised about the QUESTION belong to no single sitting, so
    # they are not in flags_by_attempt and would otherwise never appear again --
    # the teacher would mark a question, reload, and see no trace of it. Keyed by
    # (checkpoint, question) and merged into every session that contains it.
    question_flags = {}
    for checkpoint_id in checkpoint_ids:
        for flag in models.get_checkpoint_flags(checkpoint_id=checkpoint_id):
            if flag['checkpoint_attempt_id'] is None and flag['student_id'] is None:
                question_flags.setdefault(
                    (checkpoint_id, flag['question_index']), []).append(flag)

    sessions = []
    for attempt in attempts:
        answers = answers_by_attempt.get(attempt['id'], [])
        questions = _checkpoint_snapshot_questions(attempt)
        flags = flags_by_attempt.get(attempt['id'], {})
        # Only reports still awaiting a decision take the question out of the score.
        # Once ruled on, the verdict decides: 'abgelehnt' puts it back on the
        # student (they redo it), the other two leave it out for good.
        open_flags = {idx for idx, rows in flags.items()
                      if any(r['status'] == 'offen' for r in rows)}
        review = _checkpoint_question_review(answers, open_flags)

        # Scores in `review` are re-derived from the answer log. A hand-set score
        # is not in that log by definition, so it has to be laid over the top --
        # otherwise the page would keep showing the number the teacher corrected.
        manual_scores = (json.loads(attempt['question_scores_manual_json'])
                         if attempt.get('question_scores_manual_json') else {})

        for entry in review:
            entry['scored_manual'] = str(entry['question_index']) in manual_scores
            if entry['scored_manual']:
                entry['scored'] = manual_scores[str(entry['question_index'])]
                entry['scored_without_duplicates'] = entry['scored']
            entry['flags'] = (flags.get(entry['question_index'], [])
                              + question_flags.get((attempt['checkpoint_id'],
                                                    entry['question_index']), []))
            entry['flag_class_count'] = open_by_question.get(
                (attempt['checkpoint_id'], entry['question_index']), 0)
            question = (questions[entry['question_index']]
                        if entry['question_index'] < len(questions) else None)
            entry['question_text'] = question.get('text') if question else None
            entry['question_type'] = question.get('type', 'multiple_choice') if question else None
            entry['rubric'] = question.get('rubric') if question else None

            # Multiple choice is logged as option indices. Resolve them to text
            # once, here, so the review UI and both exports read the same thing --
            # a bare "[0]" is unreadable next to the question it answers.
            interactive = bool(question) and quiz_grading.is_interactive(entry['question_type'])
            if interactive:
                entry['correct_display'] = quiz_grading.correct_answer_text(question)
            elif question and entry['question_type'] == 'multiple_choice':
                entry['correct_display'] = _mc_option_labels(question, question.get('correct') or [])
            else:
                entry['correct_display'] = None
            for answer in entry['answers']:
                if interactive:
                    answer['answer_display'] = _resolve_interactive_answer(question, answer['answer_text'])
                elif entry['question_type'] == 'multiple_choice':
                    answer['answer_display'] = _resolve_mc_answer(question, answer['answer_text'])
                else:
                    answer['answer_display'] = None
                _mark_calibration_relevance(answer, entry['question_type'])

        has_duplicates = any(entry['duplicate_ids'] for entry in review)
        # The score the session would have had if no duplicate had been counted.
        # min() across questions, exactly as the live scoring does -- reported
        # questions left out, exactly as _score_checkpoint_session leaves them out.
        clean_scores = [entry['scored_without_duplicates'] for entry in review
                        if entry['scored_without_duplicates'] is not None]
        if clean_scores:
            suggested = min(clean_scores)
        else:
            suggested = 0 if review else attempt['score']

        sessions.append({
            'attempt': attempt,
            'questions': review,
            'has_duplicates': has_duplicates,
            'open_flag_count': len(open_flags),
            'flag_count': sum(len(rows) for rows in flags.values()),
            # Only offer a correction when it would actually change something and
            # the teacher has not already decided -- a suggestion that repeats the
            # current score is noise.
            'suggested_score': (suggested
                                if has_duplicates
                                and suggested != attempt['score']
                                and attempt.get('teacher_score') is None
                                else None),
            'answer_count': len(answers),
        })
    return sessions


def _count_by_student(sessions, attempt_ids):
    """How many of `attempt_ids` belong to each student, for the per-student buttons."""
    counts = {}
    for entry in sessions:
        if entry['attempt']['id'] in attempt_ids:
            key = entry['attempt']['student_id']
            counts[key] = counts.get(key, 0) + 1
    return counts


@app.route('/admin/checkpoint-pruefung')
@admin_required
def admin_checkpoint_pruefung():
    """Review checkpoint quiz answers, LLM verdicts and scores."""
    filters = _checkpoint_filters()
    sessions = _build_checkpoint_sessions(models.get_checkpoint_reviews(**filters))

    # Same sessions, regrouped by question. Two views over ONE model rather than two
    # queries: the question view can then never disagree with the session view about
    # a score, a flag or a duplicate. Built unconditionally because the tab has to
    # show its count either way, and it is pure aggregation over data already loaded.
    questions = checkpoint_questions.build_question_view(sessions)

    # What each batch button would actually touch, counted here so both can name a
    # real number instead of the broader "has duplicates" badge. The three numbers
    # differ on purpose: a flagged duplicate that cannot move the score is
    # abhakbar, not korrigierbar.
    correctable, _ = _double_click_corrections(sessions)
    dismissible, _ = _double_click_dismissals(sessions)
    correctable_ids = {attempt_id for attempt_id, _score in correctable}
    correctable_by_student = _count_by_student(sessions, correctable_ids)
    dismissible_by_student = _count_by_student(sessions, set(dismissible))

    return render_template('admin/checkpoint_pruefung.html',
                           sessions=sessions,
                           questions=questions,
                           # Which grouping is on screen. A query arg, not a session
                           # preference: the tab has to survive being linked to and
                           # bookmarked, and every filter already lives in the URL.
                           ansicht=('fragen' if request.args.get('ansicht') == 'fragen'
                                    else 'sitzungen'),
                           low_confidence=checkpoint_questions.LOW_CONFIDENCE,
                           klassen=models.get_all_klassen(),
                           students=models.get_checkpoint_students(),
                           checkpoints=models.get_checkpoint_checkpoints(),
                           klasse_id=filters['klasse_id'],
                           student_id=filters['student_id'],
                           checkpoint_id=filters['checkpoint_id'],
                           date_from=filters['date_from'],
                           date_to=filters['date_to'],
                           unreviewed_only=filters['unreviewed_only'],
                           flagged_only=filters['flagged_only'],
                           show_superseded=filters['include_superseded'],
                           flag_reasons=models.CHECKPOINT_FLAG_REASONS,
                           flag_resolutions=models.CHECKPOINT_FLAG_RESOLUTIONS,
                           teacher_verdicts=models.CHECKPOINT_FLAG_TEACHER_VERDICTS,
                           flagged_session_count=sum(1 for s in sessions
                                                     if s['open_flag_count']),
                           resettable_count=sum(1 for s in sessions
                                                if not s['attempt'].get('superseded_at')),
                           duplicate_count=sum(1 for s in sessions if s['has_duplicates']),
                           correctable_count=len(correctable),
                           correctable_by_student=correctable_by_student,
                           dismissible_count=len(dismissible),
                           dismissible_by_student=dismissible_by_student)


@app.route('/admin/checkpoint-pruefung/<int:attempt_id>/bewerten', methods=['POST'])
@admin_required
def admin_checkpoint_review_save(attempt_id):
    """Save one checkpoint review: the grade, the private reason, the student note.

    Three separate things land here, and only the first two are the teacher's own
    record -- `student_feedback` is published to the student (migrate_049), so it is
    kept apart from `teacher_note` all the way down rather than merged into one
    "notes" concept in the route.

    `reviewed` comes from which submit button was pressed: "Speichern" marks the
    session checked (that is the point -- a student is shown that it happened),
    "Prüfung zurücknehmen" clears it back to unreviewed.
    """
    raw_score = request.form.get('teacher_score', '')
    note = (request.form.get('teacher_note') or '').strip()
    student_feedback = (request.form.get('student_feedback') or '').strip()
    reviewed = request.form.get('reviewed', '1') != '0'

    if raw_score == '':
        teacher_score = None          # clears the override, back to the computed score
    else:
        try:
            teacher_score = int(raw_score)
        except ValueError:
            flash('Ungültige Punktzahl.', 'danger')
            return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))
        if teacher_score not in (0, 2, 3):
            # The scale is a strict three-value category (chemie-data-contract.md
            # §3a), not a range -- a 1 here would silently break the Kern-Sperre.
            flash('Punktzahl muss 0, 2 oder 3 sein.', 'danger')
            return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    if not reviewed:
        teacher_score, note, student_feedback = None, '', ''

    models.set_checkpoint_teacher_review(attempt_id, teacher_score, note,
                                         student_feedback, session['admin_id'],
                                         reviewed=reviewed)
    flash('Prüfung zurückgenommen.' if not reviewed else 'Bewertung gespeichert.', 'success')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


@app.route('/admin/checkpoint-pruefung/<int:attempt_id>/zuruecksetzen', methods=['POST'])
@admin_required
def admin_checkpoint_reset(attempt_id):
    """Reopen one checkpoint session so the student can take it again.

    Soft reset (models.supersede_checkpoint_attempts): nothing is deleted, the
    session and its answers stay as history. This is the per-student escape hatch
    -- one student hit a bug, one session reopens.
    """
    count = models.supersede_checkpoint_attempts([attempt_id])
    flash('Checkpoint wurde zurückgesetzt — der Schüler kann ihn erneut bearbeiten.'
          if count else 'Diese Sitzung war bereits zurückgesetzt.',
          'success' if count else 'warning')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


@app.route('/admin/checkpoint-pruefung/zuruecksetzen', methods=['POST'])
@admin_required
def admin_checkpoint_reset_bulk():
    """Reopen every checkpoint session currently listed by the page's filters.

    The selection is re-derived from the posted filters rather than from a list of
    ids in the form: what gets reset is then by construction what the teacher saw,
    and a stale or tampered form cannot name a session outside it.

    Refuses an unfiltered reset. Without a Klasse, a Schüler or a Checkpoint this
    would reopen every checkpoint in the database from one click -- the one
    mistake here that is tedious to undo (each row's superseded_at would have to
    be cleared by hand).
    """
    filters = _checkpoint_filters(source=request.form, limit=5000)
    if not (filters['klasse_id'] or filters['student_id'] or filters['checkpoint_id']):
        flash('Bitte zuerst nach Klasse, Schüler oder Checkpoint filtern — '
              'ein ungefiltertes Zurücksetzen ist nicht möglich.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    # Superseded rows are never re-reset, so the listing this acts on is the live
    # one regardless of whether the history toggle was on when the form was sent.
    filters['include_superseded'] = False
    attempts = models.get_checkpoint_reviews(**filters)
    count = models.supersede_checkpoint_attempts([a['id'] for a in attempts])
    flash(f'{count} Checkpoint-Sitzung(en) zurückgesetzt.' if count
          else 'Keine offenen Sitzungen zum Zurücksetzen.',
          'success' if count else 'warning')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


DOUBLE_CLICK_NOTE = 'Doppelklick, verworfen'

# Graders that actually ran a model. The others ('mc', 'match', 'empty') are
# deterministic comparisons, and 'error' means grading never happened -- see
# _grade_warmup_answer's `source`.
LLM_GRADERS = ('llm', 'fallback')


def _double_click_corrections(sessions):
    """Split flagged sessions into what a batch correction would actually write.

    Returns (corrections, answer_ids) where corrections is [(attempt_id, score)].

    Selects on `suggested_score is not None`, which _build_checkpoint_sessions
    already defines as "has duplicates AND the score would change AND the teacher
    has not decided yet". That single condition is what keeps the batch from
    touching a grade a teacher already set by hand, so the check lives in one
    place rather than being restated here.

    Sessions flagged as double-clicks whose score would not change are left out
    entirely (Patrick's call 2026-08-28): correcting them writes nothing, and
    marking them reviewed would clear them out of the queue without anyone having
    looked at why the duplicate did not cost a point.
    """
    corrections, answer_ids = [], []
    for entry in sessions:
        if entry['suggested_score'] is None or entry['attempt'].get('superseded_at'):
            continue
        corrections.append((entry['attempt']['id'], entry['suggested_score']))
        for question in entry['questions']:
            answer_ids.extend(question['duplicate_ids'])
    return corrections, answer_ids


def _double_click_dismissals(sessions):
    """Flagged sessions the correction button can do nothing for.

    Returns (attempt_ids, answer_ids).

    A session score is min() across its questions, so lifting one question from 2
    to 3 moves nothing when another question scored 0 or needed a hint. Those
    sessions are flagged, uncorrectable, and were left with no action at all --
    they just sat in the open queue wearing a Doppelklick badge (found in
    production 2026-08-28: the correction button counted 0 while the badge counted
    many). This is the "abhaken" half: note and review mark, no grade.

    Skips what is already dealt with (reviewed) or no longer counts (superseded),
    and anything the correction button owns (`suggested_score is not None`).
    """
    attempt_ids, answer_ids = [], []
    for entry in sessions:
        attempt = entry['attempt']
        if not entry['has_duplicates'] or attempt.get('superseded_at'):
            continue
        if entry['suggested_score'] is not None or attempt.get('reviewed_at'):
            continue
        attempt_ids.append(attempt['id'])
        for question in entry['questions']:
            answer_ids.extend(question['duplicate_ids'])
    return attempt_ids, answer_ids


def _apply_double_click_dismissals(filters):
    """Run the abhaken batch over one filter selection. Returns the count."""
    filters['include_superseded'] = False
    sessions = _build_checkpoint_sessions(models.get_checkpoint_reviews(**filters))
    attempt_ids, answer_ids = _double_click_dismissals(sessions)

    count = models.bulk_mark_double_click_reviewed(
        attempt_ids, DOUBLE_CLICK_NOTE, session['admin_id'])
    models.bulk_note_checkpoint_answers(answer_ids, DOUBLE_CLICK_NOTE)
    return count


def _apply_double_click_corrections(filters):
    """Run the batch over one filter selection. Returns the number of sessions."""
    filters['include_superseded'] = False
    sessions = _build_checkpoint_sessions(models.get_checkpoint_reviews(**filters))
    corrections, answer_ids = _double_click_corrections(sessions)

    count = models.bulk_correct_double_click_attempts(
        corrections, DOUBLE_CLICK_NOTE, session['admin_id'])
    models.bulk_note_checkpoint_answers(answer_ids, DOUBLE_CLICK_NOTE)
    return count


@app.route('/admin/checkpoint-pruefung/doppelklick-korrigieren', methods=['POST'])
@admin_required
def admin_checkpoint_correct_double_clicks():
    """Correct every double-click session in the current selection in one go.

    Each one gets the score it would have had without the duplicate, the note on
    both the grade and the flagged answers, and the review mark -- which is what
    takes it out of the "nur ungeprüfte" queue and off the teacher's pile.

    Same shape as the bulk reset: the selection is re-derived server-side from the
    posted filters, and an unfiltered run is refused. The per-student button is
    this same route with student_id pinned, so it satisfies that guard by
    construction and needs no second code path.
    """
    filters = _checkpoint_filters(source=request.form, limit=5000)
    if not (filters['klasse_id'] or filters['student_id'] or filters['checkpoint_id']):
        flash('Bitte zuerst nach Klasse, Schüler oder Checkpoint filtern — '
              'ein ungefiltertes Korrigieren ist nicht möglich.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    # Two buttons, one route: the "must be filtered" guard above and the
    # server-side re-derivation of the selection are identical for both, and only
    # the write differs.
    if request.form.get('modus') == 'abhaken':
        count = _apply_double_click_dismissals(filters)
        flash(f'{count} Doppelklick-Sitzung(en) als geprüft abgehakt (ohne Notenänderung).'
              if count else 'Keine offenen Doppelklick-Sitzungen zum Abhaken in dieser Auswahl.',
              'success' if count else 'warning')
    else:
        count = _apply_double_click_corrections(filters)
        flash(f'{count} Doppelklick-Sitzung(en) korrigiert und als geprüft markiert.' if count
              else 'Keine Doppelklick-Sitzung mit Korrekturvorschlag in dieser Auswahl.',
              'success' if count else 'warning')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


@app.route('/admin/checkpoint-pruefung/meldung/<int:flag_id>/urteil', methods=['POST'])
@admin_required
def admin_checkpoint_flag_resolve(flag_id):
    """Rule on one student report of a broken checkpoint question.

    Three outcomes (models.CHECKPOINT_FLAG_RESOLUTIONS): the question is broken,
    the question is fine but sits in the wrong place, or the report is rejected and
    the student has to answer it after all. The first two leave the question out of
    that session's score for good; only 'abgelehnt' sends it back to the student.

    The verdict is stored on the flag, never on checkpoint_answer.teacher_note --
    that field is the prompt-tuning note and ships as `lehrer_notiz_antwort` in the
    calibration export, where a question-design note would be indistinguishable
    from a grading note.
    """
    status = request.form.get('status')
    if status not in models.CHECKPOINT_FLAG_RESOLUTIONS:
        flash('Unbekanntes Urteil.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    note = (request.form.get('resolution_note') or '').strip()
    models.resolve_checkpoint_flag(flag_id, status, note, session['admin_id'])
    flash(_FLAG_VERDICT_FLASH[status], 'success')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


# Keyed on every value of CHECKPOINT_FLAG_RESOLUTIONS -- a verdict added to the dict
# without a line here used to KeyError the route rather than the import.
_FLAG_VERDICT_FLASH = {
    'frage_kaputt': 'Frage als kaputt vermerkt — sie zählt für diese Sitzung nicht.',
    'kontext_falsch': 'Frage als falsch platziert vermerkt — sie zählt für diese Sitzung nicht.',
    'design_fehlerhaft': 'Frage als vom Aufgabendesign nicht gedeckt vermerkt — sie zählt für diese Sitzung nicht.',
    'abgelehnt': 'Meldung abgelehnt — der Schüler holt die Frage nach.',
}


def _checkpoint_question_wording(checkpoint_id, question_index):
    """The question as it reads RIGHT NOW, for pinning onto a flag.

    Deliberately the live subtask.quiz_json and not the session's snapshot: a
    teacher flagging a question is about to rewrite that question, and the record
    has to say which wording they were looking at when they condemned it.
    """
    subtask = models.get_subtask(checkpoint_id)
    if not subtask or not subtask.get('quiz_json'):
        return None
    try:
        questions = json.loads(subtask['quiz_json']).get('questions', [])
    except (ValueError, AttributeError):
        return None
    if 0 <= question_index < len(questions):
        return questions[question_index].get('text')
    return None


@app.route('/admin/checkpoint-pruefung/frage/<int:checkpoint_id>/<int:question_index>/markieren',
           methods=['POST'])
@admin_required
def admin_checkpoint_flag_question(checkpoint_id, question_index):
    """Flag a question as faulty without any student having reported it.

    This is a statement about the QUESTION, so it is stored with student_id NULL on
    (checkpoint_id, question_index) -- not on checkpoint_answer.teacher_verdict,
    which asks the narrower "was the KI right about this one answer?" and feeds the
    calibration export.

    It changes NO score by itself (Patrick, 2026-09-01). A confirmed student report
    drops its question from that student's min(); doing the same here would silently
    rewrite the grade of every session that ever contained the question, including
    long-finished ones. The repair is chosen per session afterwards: send the
    question back (admin_checkpoint_question_retry) or set its score by hand
    (admin_checkpoint_question_score).
    """
    status = request.form.get('status')
    if status not in models.CHECKPOINT_FLAG_TEACHER_VERDICTS:
        flash('Unbekanntes Urteil.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    models.create_checkpoint_flag(
        checkpoint_id=checkpoint_id, question_index=question_index,
        source='teacher', status=status,
        reason_text=(request.form.get('reason_text') or '').strip(),
        question_text_at_flag=_checkpoint_question_wording(checkpoint_id, question_index),
        resolved_by=session['admin_id'])
    flash(f'Frage {question_index + 1} markiert: '
          f'{models.CHECKPOINT_FLAG_TEACHER_VERDICTS[status]}. '
          'Die Punkte der Schüler ändert das nicht — dafür sind die zwei Knöpfe an '
          'der Sitzung da.', 'success')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


@app.route('/admin/checkpoint-pruefung/<int:attempt_id>/frage/<int:question_index>/nachbessern',
           methods=['POST'])
@admin_required
def admin_checkpoint_question_retry(attempt_id, question_index):
    """Send one question back to one student, without reopening the whole checkpoint.

    Reuses the machinery a rejected report already drives (get_flags_for_retry ->
    the student sees only the owed questions -> _finish_checkpoint_retry rescores
    the SAME attempt). The difference is the status: 'nachbesserung' is not capped
    at REJECTED_FLAG_RETRY_CAP, because the student is redoing the question on our
    account, not on their own.
    """
    attempt = models.get_checkpoint_attempt(attempt_id)
    if not attempt:
        flash('Diese Sitzung gibt es nicht mehr.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))
    if attempt.get('superseded_at'):
        # A reset already gives the student the whole checkpoint back. Handing one
        # question back on top of that would leave a flag nothing ever closes.
        flash('Diese Sitzung ist zurückgesetzt — der Schüler bearbeitet ohnehin den '
              'ganzen Checkpoint neu.', 'warning')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    existing = models.get_checkpoint_flags(
        checkpoint_id=attempt['checkpoint_id'], question_index=question_index,
        student_id=attempt['student_id'], statuses=('nachbesserung',))
    if existing:
        flash(f'Frage {question_index + 1} ist bei diesem Schüler schon zur '
              'Nachbesserung offen.', 'warning')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    models.create_checkpoint_flag(
        checkpoint_id=attempt['checkpoint_id'], question_index=question_index,
        source='teacher', student_id=attempt['student_id'], status='nachbesserung',
        # Bound to the session it is owed from: without it the flag is invisible to
        # the review page (which groups by attempt) and to
        # checkpoint_score_is_provisional, so the score would read as final while a
        # question is still outstanding.
        checkpoint_attempt_id=attempt['id'],
        reason_text=(request.form.get('reason_text') or '').strip(),
        question_text_at_flag=_checkpoint_question_wording(attempt['checkpoint_id'],
                                                           question_index),
        resolved_by=session['admin_id'])
    flash(f'Frage {question_index + 1} geht zurück an den Schüler — sie wird beim '
          'nächsten Öffnen des Checkpoints gestellt, ohne Punktabzug fürs Nachholen.',
          'success')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


@app.route('/admin/checkpoint-pruefung/<int:attempt_id>/frage/<int:question_index>/punkte',
           methods=['POST'])
@admin_required
def admin_checkpoint_question_score(attempt_id, question_index):
    """Set one question's score by hand -- the other repair next to a redo.

    Not the same thing as the session-level teacher_score: that one overrides the
    whole sitting and says "I have judged this session". This says "this one question
    was ours to fix", leaves the rest of the breakdown alone, and lets the session
    score follow from it.
    """
    raw = request.form.get('punkte', '')
    if raw not in ('0', '2', '3', ''):
        flash('Für eine Frage sind nur 0, 2, 3 oder „zählt nicht" möglich.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    attempt = models.get_checkpoint_attempt(attempt_id)
    if not attempt:
        flash('Diese Sitzung gibt es nicht mehr.', 'danger')
        return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))

    score, counted = _set_checkpoint_question_score(
        attempt, question_index, None if raw == '' else int(raw))
    flash(f'Frage {question_index + 1}: '
          + ('zählt nicht mehr mit' if raw == '' else f'{raw} Punkte')
          + f'. Sitzungswert jetzt {score}.', 'success')
    if not counted:
        # A session where nothing counts scores 0, and 0 is what the Kern-Sperre
        # reads -- so "excusing" every question would lock the student out instead
        # of freeing them. Say so rather than let the number quietly do it.
        flash('Jetzt zählt in dieser Sitzung keine einzige Frage mehr — der Wert '
              'steht damit auf 0 und die Kern-Sperre bleibt zu. Wolltest du die '
              'ganze Sitzung erlassen, setze stattdessen unten die Punktzahl der '
              'Sitzung.', 'warning')
    return redirect(request.referrer or url_for('admin_checkpoint_pruefung'))


def _set_checkpoint_question_score(attempt, question_index, score):
    """Write one hand-set question score into an attempt and rebuild the session
    score around it. Returns (session score, how many questions still count).

    `score`: 0, 2, 3, or None for "this question does not count".

    The stored breakdown is keyed by the question's index in the STORED quiz, as a
    string -- see the question_scores comment in student_checkpoint_finish. A key
    that is absent was never part of the sitting; a key holding None is present but
    uncounted, which is how a reported question is already recorded.
    """
    scores = (json.loads(attempt['question_scores_json'])
              if attempt.get('question_scores_json') else {})
    manual = (json.loads(attempt['question_scores_manual_json'])
              if attempt.get('question_scores_manual_json') else {})
    scores[str(question_index)] = score
    manual[str(question_index)] = score

    session_score = _consolidate_question_scores(scores)
    counted = sum(1 for v in scores.values() if v is not None)

    models.update_checkpoint_attempt_scores(attempt['id'], scores, session_score,
                                            manual_scores=manual)
    models.log_analytics_event(
        event_type='checkpoint_question_rescored', user_id=session['admin_id'],
        user_type='admin',
        metadata={'attempt_id': attempt['id'], 'question_index': question_index,
                  'score': score, 'session_score': session_score})
    return session_score, counted


@app.route('/admin/checkpoint-pruefung/antwort/<int:answer_id>/urteil', methods=['POST'])
@admin_required
def admin_checkpoint_answer_verdict(answer_id):
    """Save the teacher's own verdict on one answer (calibration only, no score change)."""
    raw_verdict = request.form.get('teacher_verdict', '')
    note = (request.form.get('teacher_note') or '').strip()
    verdict = None if raw_verdict == '' else (1 if raw_verdict == '1' else 0)

    models.set_checkpoint_answer_verdict(answer_id, verdict, note)
    return jsonify({'ok': True, 'teacher_verdict': verdict})


def _checkpoint_export_rows(sessions):
    """Flatten the review model to one row per logged answer -- the shape both
    exports share, so CSV and JSON can never drift apart in what they contain."""
    rows = []
    for entry in sessions:
        attempt = entry['attempt']
        for question in entry['questions']:
            # Newest report on this question, if any. Flat columns rather than a
            # nested structure: this file is read in a spreadsheet, and a report is
            # a property of the question the row is about.
            flag = question['flags'][0] if question.get('flags') else {}
            flag_columns = {
                'gemeldet': 1 if flag else 0,
                'meldung_grund_code': flag.get('reason_code'),
                'meldung_grund': models.CHECKPOINT_FLAG_REASONS.get(flag.get('reason_code')),
                'meldung_text': flag.get('reason_text'),
                'meldung_status': flag.get('status'),
                'meldung_urteil_notiz': flag.get('resolution_note'),
            }
            if flag and not question['answers']:
                # A report costs nothing to make and needs no draft answer. Without
                # this row the report would be missing from the export entirely --
                # exactly the questions worth looking at.
                rows.append({
                    'zeitpunkt': flag.get('created_at'),
                    'schueler': attempt['student_name'],
                    'schueler_id': attempt['student_id'],
                    'thema': attempt['task_name'],
                    'checkpoint': attempt['subtask_name'],
                    'kern_standard': attempt['kern_standard_tag'],
                    'frage_nr': question['question_index'] + 1,
                    'frage_typ': question['question_type'],
                    'frage': question['question_text'],
                    'bewertungskriterien': question['rubric'],
                    'versuch_nr': None,
                    'antwort': None, 'antwort_roh': None,
                    'richtige_antwort': question.get('correct_display'),
                    'ki_urteil': None, 'ki_feedback': None, 'grader': None,
                    'modell': None, 'prompt_version': None, 'ki_konfidenz': None,
                    'tipps_vorher': None, 'aufgegeben': 0,
                    'lehrer_urteil': None, 'lehrer_notiz_antwort': None,
                    'ki_weicht_ab': 0, 'antwort_war_richtig': None,
                    'doppelklick_verdacht': 0,
                    'session_score': attempt['score'],
                    'lehrer_score': attempt.get('teacher_score'),
                    'score_gueltig': attempt['effective_score'],
                    'lehrer_notiz_session': attempt.get('teacher_note'),
                    **flag_columns,
                })
            for answer in question['answers']:
                rows.append({
                    'zeitpunkt': answer['timestamp'],
                    'schueler': attempt['student_name'],
                    'schueler_id': attempt['student_id'],
                    'thema': attempt['task_name'],
                    'checkpoint': attempt['subtask_name'],
                    'kern_standard': attempt['kern_standard_tag'],
                    'frage_nr': question['question_index'] + 1,
                    'frage_typ': question['question_type'],
                    'frage': question['question_text'],
                    'bewertungskriterien': question['rubric'],
                    'versuch_nr': answer['attempt_no'],
                    # Readable option text for multiple choice, raw stored value
                    # beside it: a spreadsheet reader wants the option, an analysis
                    # of the log wants the exact index that was clicked.
                    'antwort': answer.get('answer_display') or answer['answer_text'],
                    'antwort_roh': answer['answer_text'],
                    'richtige_antwort': question.get('correct_display'),
                    'ki_urteil': answer['correct'],
                    'ki_feedback': answer['feedback'],
                    'grader': answer['grader'],
                    'modell': answer['llm_model'],
                    'prompt_version': answer.get('prompt_version'),
                    # How sure the model was of its own verdict (migrate_052). NULL
                    # for every row no LLM graded. Nothing gates on it -- it exists so
                    # a threshold can be set on real answers to the questions actually
                    # in use, rather than replayed against a retired question set.
                    'ki_konfidenz': answer.get('judgment_confidence'),
                    'tipps_vorher': answer['hints_used_before'],
                    'aufgegeben': answer['gave_up'],
                    'lehrer_urteil': answer.get('teacher_verdict'),
                    'lehrer_notiz_antwort': answer.get('teacher_note'),
                    # Disagreement is the signal the whole export exists for: it is
                    # computed here rather than left to the reader, so a spreadsheet
                    # filter finds it without a formula.
                    #
                    # teacher_verdict answers the admin UI's question "War die
                    # KI-Bewertung richtig?" (ja/nein) -- it is NOT what the answer
                    # was. So a 0 IS the disagreement, and nothing needs comparing
                    # against `correct`. The old `teacher_verdict != correct` test
                    # reported the exact opposite on every row where the teacher
                    # confirmed a "falsch" or overruled one (72 of 103 labelled rows
                    # in the 2026-08-26 export).
                    'ki_weicht_ab': (1 if answer.get('teacher_verdict') == 0 else 0),
                    # What the answer actually was, derived rather than left to the
                    # reader: `correct` when the teacher confirmed the KI, its inverse
                    # when they overruled it. NULL while the answer is unjudged.
                    'antwort_war_richtig': (None if answer.get('teacher_verdict') is None
                                            or answer.get('correct') is None
                                            else (int(answer['correct'])
                                                  if answer['teacher_verdict'] == 1
                                                  else 1 - int(answer['correct']))),
                    'doppelklick_verdacht': 1 if answer['id'] in question['duplicate_ids'] else 0,
                    'session_score': attempt['score'],
                    'lehrer_score': attempt.get('teacher_score'),
                    'score_gueltig': attempt['effective_score'],
                    'lehrer_notiz_session': attempt.get('teacher_note'),
                    **flag_columns,
                })
    return rows


def _checkpoint_export_sessions(**filters):
    """Run the review query with the page's filters and build the display model --
    shared by both export routes so an export always matches what is on screen."""
    attempts = models.get_checkpoint_reviews(**filters)
    return _build_checkpoint_sessions(attempts)


def _checkpoint_filters(source=None, limit=300):
    """Read the review page's filter arguments.

    `source` defaults to request.args (the page and both exports); the bulk-reset
    route passes request.form so a reset acts on exactly the selection the teacher
    was looking at, resolved server-side rather than from a client-supplied id list.
    """
    args = request.args if source is None else source
    return {
        'klasse_id': args.get('klasse_id', type=int),
        'student_id': args.get('student_id', type=int),
        'checkpoint_id': args.get('checkpoint_id', type=int),
        'date_from': args.get('von') or None,
        'date_to': args.get('bis') or None,
        'unreviewed_only': args.get('offen') == '1',
        'flagged_only': args.get('gemeldet') == '1',
        'include_superseded': args.get('verlauf') == '1',
        'limit': limit,
    }


def _checkpoint_export_filters():
    """Read the same filter arguments the review page uses."""
    return _checkpoint_filters(limit=5000)


@app.route('/admin/checkpoint-pruefung/export.csv')
@admin_required
def admin_checkpoint_export_csv():
    """One row per logged answer, for scanning in a spreadsheet."""
    import csv
    import io

    rows = _checkpoint_export_rows(_checkpoint_export_sessions(**_checkpoint_export_filters()))
    buffer = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else ['zeitpunkt', 'schueler', 'frage', 'antwort']
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=';')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    # utf-8-sig: Excel opens a plain UTF-8 CSV as Latin-1 and mangles every umlaut.
    return Response(
        buffer.getvalue().encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition':
                 f'attachment; filename=checkpoints_{datetime.now().strftime("%Y-%m-%d")}.csv'}
    )


@app.route('/admin/checkpoint-pruefung/export.json')
@admin_required
def admin_checkpoint_export_json():
    """Nested per session, with full question, rubric and feedback text -- the shape
    to hand to an LLM when looking for weaknesses in the grading prompt."""
    sessions = _checkpoint_export_sessions(**_checkpoint_export_filters())

    export = {
        'exported_at': datetime.now().isoformat(),
        'prompt_version': llm_grading.prompt_version_for(llm_grading.CHECKPOINT_SYSTEM_PROMPT),
        'llm_model': config.LLM_MODEL,
        'sessions': [{
            'student': entry['attempt']['student_name'],
            'student_id': entry['attempt']['student_id'],
            'thema': entry['attempt']['task_name'],
            'checkpoint': entry['attempt']['subtask_name'],
            'kern_standard': entry['attempt']['kern_standard_tag'],
            'zeitpunkt': entry['attempt']['timestamp'],
            'score_berechnet': entry['attempt']['score'],
            'score_lehrer': entry['attempt'].get('teacher_score'),
            'score_gueltig': entry['attempt']['effective_score'],
            'lehrer_notiz': entry['attempt'].get('teacher_note'),
            'doppelklick_verdacht': entry['has_duplicates'],
            # The score is not final while a report on it is undecided -- see
            # models.checkpoint_score_is_provisional. Exported so nothing
            # downstream reads a provisional number as a grade.
            'score_vorlaeufig': bool(entry['open_flag_count']),
            'fragen': [{
                'nr': question['question_index'] + 1,
                'typ': question['question_type'],
                'frage': question['question_text'],
                'bewertungskriterien': question['rubric'],
                'richtige_antwort': question.get('correct_display'),
                'punkte': question['scored'],
                'punkte_ohne_doppelklicks': question['scored_without_duplicates'],
                # Structured, not free text: "which questions did students report,
                # for what reason, and what did the teacher decide" is the question
                # this half of the export exists to answer.
                'meldungen': [{
                    'grund_code': flag['reason_code'],
                    'grund': models.CHECKPOINT_FLAG_REASONS.get(flag['reason_code']),
                    'grund_text': flag['reason_text'],
                    'status': flag['status'],
                    'urteil_notiz': flag['resolution_note'],
                    'gemeldet_am': flag['created_at'],
                    'entschieden_am': flag['resolved_at'],
                    'quelle': flag['source'],
                    'wortlaut_bei_meldung': flag['question_text_at_flag'],
                } for flag in question.get('flags', [])],
                'versuche': [{
                    'nr': answer['attempt_no'],
                    'zeitpunkt': answer['timestamp'],
                    'antwort': answer.get('answer_display') or answer['answer_text'],
                    'antwort_roh': answer['answer_text'],
                    'ki_urteil': answer['correct'],
                    'ki_feedback': answer['feedback'],
                    'grader': answer['grader'],
                    'modell': answer['llm_model'],
                    'prompt_version': answer.get('prompt_version'),
                    'ki_konfidenz': answer.get('judgment_confidence'),
                    'tipps_vorher': answer['hints_used_before'],
                    'aufgegeben': bool(answer['gave_up']),
                    'lehrer_urteil': answer.get('teacher_verdict'),
                    # Whether the KI was right -- not what the answer was. Both are
                    # exported because reading the first as the second inverts the
                    # ground truth on every overruled row (see _checkpoint_export_rows).
                    'antwort_war_richtig': (None if answer.get('teacher_verdict') is None
                                            or answer.get('correct') is None
                                            else (int(answer['correct'])
                                                  if answer['teacher_verdict'] == 1
                                                  else 1 - int(answer['correct']))),
                    'lehrer_notiz': answer.get('teacher_note'),
                    'doppelklick_verdacht': answer['id'] in question['duplicate_ids'],
                } for answer in question['answers']],
            } for question in entry['questions']],
        } for entry in sessions],
    }

    return Response(
        json.dumps(export, ensure_ascii=False, indent=2),
        mimetype='application/json; charset=utf-8',
        headers={'Content-Disposition':
                 f'attachment; filename=checkpoints_{datetime.now().strftime("%Y-%m-%d")}.json'}
    )


@app.route('/admin/quiz-statistik')
@admin_required
def admin_quiz_statistik():
    """Quiz answer statistics grouped by topic and task."""
    klasse_id = request.args.get('klasse_id', type=int)
    task_id = request.args.get('task_id', type=int)
    only_attempted = request.args.get('attempted', '1') != '0'

    stats = models.get_quiz_stats_by_topic(klasse_id=klasse_id, task_id=task_id, only_attempted=only_attempted)
    klassen = models.get_all_klassen()
    tasks = models.get_all_tasks()

    return render_template('admin/quiz_statistik.html',
                           stats=stats,
                           klassen=klassen,
                           tasks=tasks,
                           klasse_id=klasse_id,
                           task_id=task_id,
                           only_attempted=only_attempted,
                           llm_enabled=config.LLM_ENABLED)


@app.route('/admin/quiz-statistik/export.json')
@admin_required
def admin_quiz_statistik_export():
    """Export full quiz stats as JSON for offline analysis and question redesign."""
    from datetime import datetime
    klasse_id = request.args.get('klasse_id', type=int)
    task_id = request.args.get('task_id', type=int)
    only_attempted = request.args.get('attempted', '1') != '0'

    stats = models.get_quiz_stats_by_topic(klasse_id=klasse_id, task_id=task_id,
                                           only_attempted=only_attempted, for_export=True)

    klasse_name = None
    task_name = None
    if klasse_id:
        klassen = models.get_all_klassen()
        match = next((k for k in klassen if k['id'] == klasse_id), None)
        klasse_name = match['name'] if match else None
    if task_id:
        tasks = models.get_all_tasks()
        match = next((t for t in tasks if t['id'] == task_id), None)
        task_name = match['name'] if match else None

    def build_section_label(sec):
        if sec['is_topic_quiz']:
            return 'Thema-Quiz'
        return f"Aufgabe {sec['subtask_position']}"

    def build_question(q):
        out = {
            'type': q['type'],
            'text': q['text'],
            'total_attempts': q['total'],
            'correct_count': q['correct_count'],
            'pass_rate': round(q['correct_count'] / q['total'], 2) if q['total'] else 0.0,
        }
        if q['type'] == 'multiple_choice':
            out['options'] = q.get('options', [])
        else:
            out['answers'] = q.get('answers', [])
        return out

    export = {
        'exported_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'filters': {
            'klasse': klasse_name,
            'topic': task_name,
            'only_attempted': only_attempted,
        },
        'topics': [
            {
                'name': topic['task_name'],
                'sections': [
                    {
                        'label': build_section_label(sec),
                        'questions': [build_question(q) for q in sec['questions']],
                    }
                    for sec in topic['sections']
                ],
            }
            for topic in stats
        ],
    }

    filename = f"quiz-export-{datetime.now().strftime('%Y-%m-%d')}.json"
    response = jsonify(export)
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@app.route('/admin/quiz-statistik/filter-noise', methods=['POST'])
@admin_required
def admin_filter_noise():
    """LLM noise filter for free-text quiz answers. On-demand, admin only."""
    if not config.LLM_ENABLED:
        return jsonify({'noise': [], 'error': 'LLM not configured'})
    data = request.get_json(force=True) or {}
    question = data.get('question', '').strip()
    answers = data.get('answers', [])
    if not question or not answers:
        return jsonify({'noise': [], 'error': 'missing data'})
    from llm_grading import filter_noise_answers
    noise = filter_noise_answers(question, answers)
    return jsonify({'noise': noise})


# ============ Admin: Network Whitelist ============

@app.route('/admin/netzwerk-whitelist')
@admin_required
def admin_netzwerk_whitelist():
    """Live-computed list of external domains referenced by material links,
    for pasting into a school-firewall whitelist (e.g. UCS@school Internetregeln)."""
    domains = models.get_external_link_domains()
    return render_template('admin/netzwerk_whitelist.html', domains=domains)


# ============ Admin: Error Logs ============

@app.route('/admin/errors')
@admin_required
def admin_errors():
    """View error logs with pagination and filtering."""
    # Trigger cleanup of old logs (30 days)
    deleted_count = models.cleanup_old_error_logs(days=30)

    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    # Get filter parameter
    level_filter = request.args.get('level', None)
    if level_filter and level_filter.upper() not in ['ERROR', 'WARNING', 'CRITICAL']:
        level_filter = None

    # Get logs and stats
    logs = models.get_error_logs(limit=per_page, offset=offset, level_filter=level_filter)
    total_count = models.get_error_log_count(level_filter=level_filter)
    stats = models.get_error_log_stats()

    # Calculate pagination info
    total_pages = (total_count + per_page - 1) // per_page

    return render_template('admin/errors.html',
                         logs=logs,
                         stats=stats,
                         page=page,
                         total_pages=total_pages,
                         total_count=total_count,
                         level_filter=level_filter,
                         deleted_count=deleted_count)


@app.route('/admin/errors/clear', methods=['POST'])
@admin_required
def admin_errors_clear():
    """Clear all error logs."""
    count = models.clear_all_error_logs()
    flash(f'{count} Fehlerprotokolle gelöscht.', 'success')
    return redirect(url_for('admin_errors'))


# ============ Admin: LLM Check ============

LLM_CHECK_DEFAULTS = {
    'quiz': {
        'question_text': 'Was ist ein Computervirus?',
        'expected_or_rubric': 'Schadprogramm, verbreitet sich selbst',
        'student_answer': 'Ein Vieres ist ein schädliches Programm.',
    },
    'noise': {
        'question_text': 'Was ist ein Cookie?',
        'answers_text': 'speichert Website-Infos: 5\nasdf: 3\nkeine Ahnung: 2',
    },
    'artifact': {
        'criteria_text': 'Nennt mindestens 3 Beispiele für persönliche Daten\nErklärt was ein sicheres Passwort ausmacht',
        'extracted_text': 'Persönliche Daten sind zum Beispiel Name, Adresse und Geburtsdatum. Ein gutes Passwort ist lang und enthält Zahlen, Buchstaben und Sonderzeichen.',
    },
}


@app.route('/admin/llm-check', methods=['GET', 'POST'])
@admin_required
def admin_llm_check():
    """Diagnostic page: show LLM config and run live test requests."""
    kind = request.form.get('kind', 'quiz')
    form = {**LLM_CHECK_DEFAULTS.get(kind, {}), **{k: v for k, v in request.form.items() if k != 'kind'}}
    result = None

    if request.method == 'POST':
        if kind == 'noise':
            answers = []
            for line in form.get('answers_text', '').splitlines():
                if ':' in line:
                    text, count = line.rsplit(':', 1)
                    answers.append({'text': text.strip(), 'count': int(count.strip() or 0)})
            result = llm_grading.diagnostic_call('noise', question_text=form['question_text'], answers=answers)
        elif kind == 'artifact':
            criteria = [c.strip() for c in form.get('criteria_text', '').splitlines() if c.strip()]
            result = llm_grading.diagnostic_call('artifact', extracted_text=form['extracted_text'], criteria=criteria)
        else:
            result = llm_grading.diagnostic_call(
                'quiz',
                question_text=form['question_text'],
                expected_or_rubric=form['expected_or_rubric'],
                student_answer=form['student_answer'],
            )

    return render_template('admin/llm_check.html',
                          llm_enabled=config.LLM_ENABLED,
                          llm_model=config.LLM_MODEL,
                          llm_provider=config.LLM_PROVIDER,
                          llm_base_url=config.LLM_BASE_URL,
                          llm_timeout=config.LLM_TIMEOUT,
                          llm_artifact_timeout=config.LLM_ARTIFACT_TIMEOUT,
                          kind=kind, form=form, result=result)


# ============ Admin: Analytics ============

@app.route('/admin/analytics')
@admin_required
def admin_analytics():
    """View analytics overview."""
    # Trigger cleanup of old analytics events (210 days)
    deleted_count = models.cleanup_old_analytics_events(days=210)

    # Get overview statistics
    stats = models.get_analytics_overview()

    return render_template('admin/analytics.html',
                         stats=stats,
                         deleted_count=deleted_count)


@app.route('/admin/analytics/student/<int:student_id>')
@admin_required
def admin_student_activity(student_id):
    """View individual student activity log."""
    student = models.get_student(student_id)
    if not student:
        flash('Schüler nicht gefunden.', 'danger')
        return redirect(url_for('admin_analytics'))

    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page

    # Get date range filters
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)

    # Get activity log
    events = models.get_analytics_events(
        limit=per_page,
        offset=offset,
        user_id=student_id,
        user_type='student',
        date_from=date_from,
        date_to=date_to
    )

    # Get total count for pagination
    total_count = models.get_analytics_count(
        user_id=student_id,
        user_type='student',
        date_from=date_from,
        date_to=date_to
    )
    total_pages = (total_count + per_page - 1) // per_page

    # Get summary statistics
    summary = models.get_student_activity_summary(
        student_id=student_id,
        date_from=date_from,
        date_to=date_to
    )

    gate_attempts = models.get_artifact_gate_attempts_for_student(student_id)

    return render_template('admin/student_activity.html',
                         student=student,
                         events=events,
                         summary=summary,
                         page=page,
                         total_pages=total_pages,
                         total_count=total_count,
                         date_from=date_from,
                         date_to=date_to,
                         gate_attempts=gate_attempts)


# ============ Admin: Unterricht (Lessons) ============

@app.route('/admin/klasse/<int:klasse_id>/unterricht')
@admin_required
def admin_unterricht(klasse_id):
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))
    today = date.today().isoformat()
    return redirect(url_for('admin_unterricht_datum', klasse_id=klasse_id, datum=today))


@app.route('/admin/klasse/<int:klasse_id>/unterricht/<datum>')
@admin_required
def admin_unterricht_datum(klasse_id, datum):
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))

    unterricht_id = models.create_or_get_unterricht(klasse_id, datum)

    with models.db_session() as conn:
        # Get lesson comment
        unterricht = conn.execute('SELECT kommentar FROM unterricht WHERE id = ?', (unterricht_id,)).fetchone()
        lesson_comment = unterricht['kommentar'] if unterricht else None

        # Get students with ratings
        students = conn.execute('''
            SELECT us.*, s.nachname, s.vorname
            FROM unterricht_student us
            JOIN student s ON us.student_id = s.id
            WHERE us.unterricht_id = ?
            ORDER BY s.nachname, s.vorname
        ''', (unterricht_id,)).fetchall()
        students = [dict(s) for s in students]

    return render_template('admin/unterricht.html', klasse=klasse, datum=datum, unterricht_id=unterricht_id,
                           students=students, lesson_comment=lesson_comment)


@app.route('/admin/klasse/<int:klasse_id>/unterricht/<datum>/auto-attendance', methods=['POST'])
@admin_required
def admin_auto_attendance(klasse_id, datum):
    """Auto-fill attendance from student login data."""
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        return jsonify({'error': 'Klasse nicht gefunden'}), 404
    result = models.auto_fill_attendance(klasse_id, datum)
    return jsonify(result)


@app.route('/admin/klasse/<int:klasse_id>/unterricht/<datum>/next')
@admin_required
def admin_unterricht_next(klasse_id, datum):
    """Navigate to next week's class date."""
    next_date = models.get_next_class_date(klasse_id, datum)
    return redirect(url_for('admin_unterricht_datum', klasse_id=klasse_id, datum=next_date))


@app.route('/admin/klasse/<int:klasse_id>/unterricht/<datum>/prev')
@admin_required
def admin_unterricht_prev(klasse_id, datum):
    """Navigate to previous week's class date."""
    prev_date = models.get_previous_class_date(klasse_id, datum)
    return redirect(url_for('admin_unterricht_datum', klasse_id=klasse_id, datum=prev_date))


@app.route('/admin/unterricht/<int:unterricht_id>/bewertung', methods=['POST'])
@admin_required
def admin_unterricht_bewertung(unterricht_id):
    student_id = request.form['student_id']
    anwesend = 1 if request.form.get('anwesend') else 0
    # New rating system: '-', 'ok', '+'
    admin_selbst = request.form.get('admin_selbststaendigkeit', 'ok')
    admin_respekt = request.form.get('admin_respekt', 'ok')
    admin_fortschritt = request.form.get('admin_fortschritt', 'ok')
    admin_kommentar = request.form.get('admin_kommentar', '')

    models.update_unterricht_student(
        unterricht_id, int(student_id),
        anwesend, admin_selbst, admin_respekt, admin_fortschritt, admin_kommentar
    )

    return jsonify({'status': 'ok'})


@app.route('/admin/unterricht/<int:unterricht_id>/kommentar', methods=['POST'])
@admin_required
def admin_unterricht_kommentar(unterricht_id):
    """Save lesson-wide comment"""
    kommentar = request.form.get('kommentar', '')

    with models.db_session() as conn:
        conn.execute('UPDATE unterricht SET kommentar = ? WHERE id = ?', (kommentar, unterricht_id))
        conn.commit()

    return jsonify({'status': 'ok'})


# ============ Student Dashboard ============

@app.route('/schueler')
@student_required
def student_dashboard():
    student_id = session['student_id']
    student = models.get_student(student_id)
    klassen = models.get_student_klassen(student_id)

    # Get current task for each class
    tasks_by_klasse = {}
    for klasse in klassen:
        task = models.get_student_task(student_id, klasse['id'])
        if task:
            # Get only VISIBLE subtasks for this student
            visible_subtasks = models.get_visible_subtasks_for_student(
                student_id, klasse['id'], task['task_id']
            )
            visible_subtask_ids = {s['id'] for s in visible_subtasks}

            # Get progress for all subtasks
            all_subtasks = models.get_student_subtask_progress(task['id'])

            # Filter to show only visible subtasks with their progress
            visible_with_progress = [s for s in all_subtasks if s['id'] in visible_subtask_ids]

            task['subtasks'] = visible_with_progress
            # Count only path-required subtasks for progress (excludes Einführung/is_intro subtasks)
            required_subtasks = [s for s in visible_with_progress if s.get('required', True) and not s.get('is_intro')]
            task['total_subtasks'] = len(required_subtasks)
            task['completed_subtasks'] = sum(1 for s in required_subtasks if s['erledigt'])

            # Find first incomplete subtask name for preview
            next_subtask = next((s for s in visible_with_progress if not s['erledigt']), None)
            task['next_task_preview'] = (
                aufgabe_titel(next_subtask['beschreibung'])
                if next_subtask and next_subtask.get('beschreibung') else None)
        tasks_by_klasse[klasse['id']] = task

    # Compute next queued topic per class
    next_topics = {}
    for klasse in klassen:
        task = tasks_by_klasse.get(klasse['id'])
        queue = models.get_topic_queue(klasse['id'])
        if not queue:
            continue

        if task and task.get('abgeschlossen') and task.get('task_id'):
            # Active completed topic → get next in queue
            nxt = models.get_next_queued_topic(klasse['id'], task['task_id'])
            if nxt:
                next_topics[klasse['id']] = nxt
        elif not task:
            # No active topic → find first queue item not yet done
            all_student_tasks = models.get_all_student_tasks(student_id, klasse['id'])
            done_task_ids = {st['task_id'] for st in all_student_tasks}
            for q in queue:
                if q['task_id'] not in done_task_ids:
                    next_topics[klasse['id']] = q
                    break

    # Fetch sidequests per class
    sidequests_by_klasse = {}
    for klasse in klassen:
        sidequests_by_klasse[klasse['id']] = models.get_student_sidequests(student_id, klasse['id'])

    # Completed topics per class, plus reopened-checkpoint attention items.
    # The archive is opt-in per class; the reopened notice is not -- it is
    # actionable rather than archival (see migrate_051).
    reopened_by_module = {r['module_id']: r
                          for r in models.get_reopened_checkpoint_topics(student_id)}
    completed_by_klasse = {}
    for klasse in klassen:
        completed_by_klasse[klasse['id']] = _build_completed_topic_list(
            models.get_completed_student_tasks(student_id, klasse['id']),
            reopened_by_module,
            bool(klasse.get('show_completed_topics')),
            klasse.get('klassenstufe'),
        )

    # Check if practice mode has questions available
    has_warmup_pool = bool(models.get_warmup_question_pool(student_id))

    return render_template('student/dashboard.html', student=student, klassen=klassen,
                           tasks_by_klasse=tasks_by_klasse,
                           next_topics=next_topics,
                           sidequests_by_klasse=sidequests_by_klasse,
                           completed_by_klasse=completed_by_klasse,
                           student_path=student.get('lernpfad'),
                           has_warmup_pool=has_warmup_pool)


def _stufe_matches_klassenstufe(stufe, klassenstufe):
    """Does a topic's Stufe cover a class's Klassenstufe?

    Not an equality test: task.stufe is free text and routinely a range --
    '5/6', '11/12' -- for topics deliberately written for two years at once,
    while klasse.klassenstufe is a single int. '11/12' must match both 11 and
    12. Legacy and Seilbahn spellings ('11s') reduce to their digits.

    Fails open on purpose. Most classes still carry klassenstufe = NULL, and a
    strict test would silently blank the feature for them; an unreadable or
    missing value on either side means "show it", not "hide it".
    """
    if klassenstufe is None or not stufe:
        return True
    levels = {int(n) for n in re.findall(r'\d+', str(stufe))}
    if not levels:
        return True
    return int(klassenstufe) in levels


def _build_completed_topic_list(completed, reopened_by_module, show_archive, klassenstufe):
    """Decide what a class's 'Abgeschlossene Themen' section shows.

    `completed` is newest-first from models.get_completed_student_tasks.
    `reopened_by_module` maps task_id -> the reset row (student_feedback,
    superseded_at) for checkpoints the student has not retaken.
    `show_archive` is the per-class opt-in (klasse.show_completed_topics).
    `klassenstufe` is the class's year, or None if it was never set.

    Off by default means the latest finished Thema only -- enough to get back to
    it, not a wall of history. Opting in shows all of them. Either way the list
    is filtered to the class's own year, so last year's topics stop following a
    student around.

    A reopened checkpoint changes how an entry is *drawn*, never whether it is
    in the list (Patrick's call): a student who is being asked to redo something
    should meet it in the same place as everything else they have finished.
    """
    entries = [c for c in completed
               if _stufe_matches_klassenstufe(c.get('stufe'), klassenstufe)]
    if not show_archive:
        entries = entries[:1]

    result = []
    for c in entries:
        reopened = reopened_by_module.get(c['task_id'])
        result.append({
            'task_id': c['task_id'],
            'name': c['name'],
            'is_seilbahn': c.get('is_seilbahn'),
            'reopened': bool(reopened),
            'feedback': reopened.get('student_feedback') if reopened else None,
        })
    return result


@app.route('/schueler/bericht')
@student_required
def student_bericht():
    """Generate and download student's own progress report PDF (student-facing version)."""
    student_id = session['student_id']

    # Get report data (summary only for students)
    report_data = models.get_report_data_for_student(student_id, report_type='summary')

    if not report_data:
        flash('Fehler beim Erstellen des Berichts.', 'error')
        return redirect(url_for('student_dashboard'))

    # Generate PDF with student-friendly framing
    pdf_buffer = generate_student_self_report_pdf(report_data)

    # Prepare filename
    student = report_data['student']
    timestamp = datetime.now().strftime('%Y%m%d')
    filename = f"mein_lernfortschritt_{timestamp}.pdf"

    # Log the download
    models.log_analytics_event(
        event_type='report_download',
        user_id=student_id,
        user_type='student',
        metadata={'report_type': 'self_report'}
    )

    return Response(
        pdf_buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/schueler/thema/<slug>')
@student_required
def student_klasse(slug):
    student_id = session['student_id']
    student = models.get_student(student_id)

    # Resolve slug to student_task + klasse
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task or not klasse:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    klasse_id = klasse['id']
    subtasks = []
    all_subtasks = []
    current_subtask = None
    materials = []
    quiz_attempts = []

    subtask_quiz_status = {}  # {subtask_id: True/False} for subtasks with quizzes
    quiz_bestanden = False

    if task:
        # Get ALL subtasks with completion status
        all_subtasks = models.get_student_subtask_progress(task['id'])
        quiz_attempts = models.get_quiz_attempts(task['id'])  # topic-level only (subtask_id IS NULL)

        # Check if topic quiz was passed
        quiz_bestanden = any(a['bestanden'] for a in quiz_attempts)

        # Compute subtask quiz pass status for progress dots
        for st in all_subtasks:
            if st.get('quiz_json'):
                subtask_quiz_status[st['id']] = models.has_passed_subtask_quiz(task['id'], st['id'])

        # Get visible subtasks based on path/visibility rules (includes 'required' flag)
        visible_subtasks_with_flags = models.get_visible_subtasks_for_student(
            student_id, klasse_id, task['task_id']
        )
        visible_map = {s['id']: s for s in visible_subtasks_with_flags}

        # Filter all_subtasks to only visible ones, merging the 'required' flag
        if visible_map:
            subtasks = []
            for st in all_subtasks:
                if st['id'] in visible_map:
                    st['required'] = visible_map[st['id']].get('required', True)
                    st['path'] = visible_map[st['id']].get('path')
                    subtasks.append(st)
        else:
            subtasks = []

        # Check if specific subtask requested via URL parameter (1-based position)
        requested_position = request.args.get('aufgabe', type=int)
        if requested_position:
            requested_subtask = _resolve_subtask_by_position(subtasks, requested_position)
            if requested_subtask:
                current_subtask = requested_subtask
            elif subtasks:
                current_subtask = _resolve_resume_subtask(subtasks, subtask_quiz_status)
        elif subtasks:
            # No position requested (dashboard "Weiter lernen", quiz Zurück/Abbrechen, etc.)
            # -- resume at actual progress, not always position 1.
            current_subtask = _resolve_resume_subtask(subtasks, subtask_quiz_status)

        # Load materials filtered by current Aufgabe
        if current_subtask:
            materials = models.get_materials_for_subtask(task['task_id'], current_subtask['id'])
        else:
            materials = models.get_materials(task['task_id'])

    # Fork/Choice: pending (unresolved) fork_groups on this task, excluded from
    # `subtasks` above. One placeholder dot per pending group, positioned by
    # where it sits among the currently-visible subtasks (see
    # docs/shared/lernmanager/fork-choice-artifact-model.md).
    pending_fork_groups = models.get_pending_fork_groups(task['task_id'], student_id) if task else []
    pending_fork_dot_positions = {}
    for fg in pending_fork_groups:
        idx = sum(1 for s in subtasks if s['reihenfolge'] < fg['min_reihenfolge'])
        pending_fork_dot_positions[idx] = fg

    # The selection screen replaces the normal subtask content once every
    # subtask before the fork is done -- checked directly against completion
    # status, not against `current_subtask` (which defaults to position 1 on
    # a fresh page load, not "first incomplete" -- see todo.md § Bugs).
    pending_fork = None
    if pending_fork_groups:
        fg = pending_fork_groups[0]
        if all(s['erledigt'] for s in subtasks if s['reihenfolge'] < fg['min_reihenfolge']):
            pending_fork = fg

    # Check for next queued topic (only when current is completed)
    next_topic = None
    if task and task.get('abgeschlossen'):
        next_topic = models.get_next_queued_topic(klasse_id, task['task_id'])

    # Capstone gate: gate on the last visible subtask (bottom card, blocks quiz/next-topic)
    capstone_gate = None
    capstone_gate_passed = False
    capstone_gate_position = None
    capstone_gate_llm_feedback = None
    capstone_gate_keyword = None
    if subtasks and subtasks[-1].get('artifact_gate_json'):
        last = subtasks[-1]
        try:
            last['artifact_gate'] = json.loads(last['artifact_gate_json'])
            capstone_gate = last
            capstone_gate_passed = bool(last.get('artifact_gate_passed'))
            capstone_gate_position = len(subtasks)
            if capstone_gate_passed and last.get('graded_artifact_json'):
                fb = models.get_artifact_feedback(student_id, last['id'])
                capstone_gate_llm_feedback = fb['feedback'] if fb else None
            if last.get('graded_artifact_json'):
                ga = json.loads(last['graded_artifact_json'])
                capstone_gate_keyword = ga.get('keyword')
        except (json.JSONDecodeError, TypeError):
            pass

    # Inline gate: gate on the current subtask when it is NOT the last subtask
    inline_gate = None
    inline_gate_passed = False
    inline_gate_position = None
    inline_gate_keyword = None
    inline_gate_llm_feedback = None
    if current_subtask and current_subtask.get('artifact_gate_json') and subtasks and current_subtask is not subtasks[-1]:
        try:
            inline_gate = json.loads(current_subtask['artifact_gate_json'])
            inline_gate_passed = bool(current_subtask.get('artifact_gate_passed'))
            inline_gate_position = subtasks.index(current_subtask) + 1
            if current_subtask.get('graded_artifact_json'):
                ga = json.loads(current_subtask['graded_artifact_json'])
                inline_gate_keyword = ga.get('keyword')
                # Mirrors the capstone card: each gate card owns the one persisted
                # feedback display for its own checkpoint.
                if inline_gate_passed:
                    fb = models.get_artifact_feedback(student_id, current_subtask['id'])
                    inline_gate_llm_feedback = fb['feedback'] if fb else None
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Parse graded_artifact_json for the active subtask (criteria-based upload widget).
    # Suppressed when the subtask has a gate — checkpoint card handles the upload instead.
    graded_artifact = None
    if current_subtask and current_subtask.get('graded_artifact_json') and not current_subtask.get('artifact_gate_json'):
        try:
            ga = json.loads(current_subtask['graded_artifact_json'])
            if ga.get('criteria') and klasse and klasse.get('llm_artifact_feedback_enabled'):
                graded_artifact = ga
        except (json.JSONDecodeError, TypeError):
            pass

    # Latest uploaded artifact file for this unit, if any -- shown as a download link next to
    # the upload widget. One file per (student, task): units use the "gradual artifact building"
    # pattern, so every checkpoint in the unit shares the same growing document.
    unit_artifact_file = models.get_student_artifact_file(student_id, task['task_id']) if task else None
    artifact_checkpoint_status, artifact_criteria, artifact_llm_feedback, artifact_last_position = _artifact_file_details(
        unit_artifact_file, subtasks, student, klasse, task['task_id'] if task else None
    )

    # Clayden-style unit connections (Baut auf / Du erreichst / Führt zu) — plain-text v1
    connections = None
    looking_forward_to = []
    if task and task.get('connections_json'):
        try:
            connections = json.loads(task['connections_json'])
        except (json.JSONDecodeError, TypeError):
            connections = None
    if task and task.get('unit_slug'):
        looking_forward_to = models.get_looking_forward_to(task['unit_slug'])

    # Checkpoints where a rejected report left a question owed. The Aufgabe is
    # already ticked off, so without this notice nothing points the student back.
    retry_checkpoint_ids = models.get_checkpoints_awaiting_retry(student_id)

    return render_template('student/klasse.html',
                           retry_checkpoint_ids=retry_checkpoint_ids,
                           connections=connections,
                           looking_forward_to=looking_forward_to,
                           student=student,
                           klasse=klasse,
                           task=task,
                           subtasks=subtasks,
                           all_subtasks=all_subtasks,
                           current_subtask=current_subtask,
                           materials=materials,
                           client_school_ok=_client_in_school_network(),
                           quiz_attempts=quiz_attempts,
                           subtask_quiz_status=subtask_quiz_status,
                           quiz_bestanden=quiz_bestanden,
                           next_topic=next_topic,
                           graded_artifact=graded_artifact,
                           capstone_gate=capstone_gate,
                           capstone_gate_passed=capstone_gate_passed,
                           capstone_gate_position=capstone_gate_position,
                           capstone_gate_llm_feedback=capstone_gate_llm_feedback,
                           inline_gate=inline_gate,
                           inline_gate_passed=inline_gate_passed,
                           inline_gate_position=inline_gate_position,
                           inline_gate_keyword=inline_gate_keyword,
                           inline_gate_llm_feedback=inline_gate_llm_feedback,
                           capstone_gate_keyword=capstone_gate_keyword,
                           student_path=student.get('lernpfad') if student else None,
                           unit_artifact_file=unit_artifact_file,
                           artifact_checkpoint_status=artifact_checkpoint_status,
                           artifact_criteria=artifact_criteria,
                           artifact_llm_feedback=artifact_llm_feedback,
                           artifact_last_position=artifact_last_position,
                           pending_fork=pending_fork,
                           pending_fork_dot_positions=pending_fork_dot_positions)


@app.route('/schueler/thema/<slug>/aufgabe/<int:position>', methods=['POST'])
@student_required
def student_toggle_subtask(slug, position):
    student_id = session['student_id']

    # Resolve slug to student_task
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        return jsonify({'status': 'error', 'message': 'Not found'}), 404

    student_task_id = task['id']

    # Resolve position to subtask
    all_subtasks = models.get_student_subtask_progress(student_task_id)
    visible_subtasks = models.get_visible_subtasks_for_student(
        student_id, klasse['id'], task['task_id']
    )
    visible_subtask_ids = {s['id'] for s in visible_subtasks}
    subtasks = [st for st in all_subtasks if st['id'] in visible_subtask_ids]
    subtask = _resolve_subtask_by_position(subtasks, position)
    if not subtask:
        return jsonify({'status': 'error', 'message': 'Not found'}), 404

    subtask_id = subtask['id']
    erledigt = request.json.get('erledigt', False)
    toggle_result = models.toggle_student_subtask(student_task_id, subtask_id, erledigt)

    # Log subtask completion
    if erledigt:
        models.log_analytics_event(
            event_type='subtask_complete',
            user_id=student_id,
            user_type='student',
            metadata={
                'student_task_id': student_task_id,
                'subtask_id': subtask_id
            }
        )

    # If subtask quiz is pending, tell the JS to redirect
    if toggle_result.get('quiz_pending'):
        quiz_url = url_for('student_quiz_subtask', slug=slug, position=position)
        return jsonify({'status': 'ok', 'task_complete': False, 'show_quiz': True, 'quiz_url': quiz_url})

    # Check if task should be auto-completed
    if models.check_task_completion(student_task_id):
        models.mark_task_complete(student_task_id)
        models.log_analytics_event(
            event_type='task_complete',
            user_id=student_id,
            user_type='student',
            metadata={'student_task_id': student_task_id}
        )
        return jsonify({'status': 'ok', 'task_complete': True})

    return jsonify({'status': 'ok', 'task_complete': False})


@app.route('/schueler/thema/<slug>/fork/<fork_group>/waehlen', methods=['POST'])
@student_required
def student_fork_choice(slug, fork_group):
    """Record a student's branch pick for a fork_group.

    Design: docs/shared/lernmanager/fork-choice-artifact-model.md decision 2 --
    the pick can be revised freely until the student completes a subtask in
    the chosen branch, then it's locked.
    """
    student_id = session['student_id']
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    branch = request.form.get('branch')
    valid_branches = models.get_fork_branches(task['task_id'], fork_group)
    if not valid_branches or branch not in valid_branches:
        flash('Diese Wahl ist nicht möglich.', 'danger')
        return redirect(url_for('student_klasse', slug=slug))

    existing = models.get_student_fork_choice(student_id, fork_group)
    if existing and models.is_fork_choice_locked(student_id, fork_group, existing):
        flash('Diese Wahl ist bereits festgelegt und kann nicht mehr geändert werden.', 'danger')
        return redirect(url_for('student_klasse', slug=slug))

    models.set_student_fork_choice(student_id, fork_group, branch)
    models.log_analytics_event(
        event_type='fork_choice',
        user_id=student_id,
        user_type='student',
        metadata={'task_id': task['task_id'], 'fork_group': fork_group, 'branch': branch}
    )
    return redirect(url_for('student_klasse', slug=slug))


def _artifact_upload_dir():
    """Computed fresh each call (not a frozen constant) so tests can override config.UPLOAD_FOLDER."""
    return os.path.join(config.UPLOAD_FOLDER, 'artefakte')


def _template_loader(task_id):
    """Resolve a gate's template_material to the file already on disk.

    A gate's min_added_words compares a submission against the template the
    student started from. That template is registered as a material of the same
    topic, so nothing new is stored -- this just finds it by name. Returns None
    on anything unexpected; artifact_checker fails the check soft.
    """
    def load(name):
        if not name or not task_id:
            return None
        for mat in models.get_materials(task_id):
            pfad = mat.get('pfad') or ''
            if pfad in (name,) or os.path.basename(pfad) == name:
                path = os.path.join(config.UPLOAD_FOLDER, pfad)
                if os.path.isfile(path):
                    with open(path, 'rb') as fh:
                        return fh.read()
        return None
    return load


def _artifact_format_error(filename, file_bytes):
    """Student-facing message when an upload's content contradicts its name.

    docx, pptx, odt, odp and sb3 are all ZIP containers, so the extension check
    alone cannot tell them apart -- a .pptx saved as .docx used to run into the
    document extractor and come back with a confusing parse error instead of
    "wrong format". Returns None when name and content agree.
    """
    ok, sniffed = content_matches_extension(filename, file_bytes)
    if ok:
        return None
    claimed = file_extension(filename).upper()
    if not sniffed:
        return (f"Diese Datei ist keine gültige {claimed}-Datei. "
                f"Speichere sie noch einmal als {claimed} und lade sie erneut hoch.")
    return (f"Diese Datei ist eine {sniffed.upper()}-Datei, heißt aber „.{claimed.lower()}“. "
            f"Speichere sie als {claimed} und lade sie noch einmal hoch.")


def _save_artifact_file(student_id, task_id, subtask_id, file_bytes, original_filename):
    """Persist the latest artifact upload for a student+task (unit), overwriting any previous file.

    Keyed by task_id, not subtask_id: units use the "gradual artifact building" pattern
    (docs/shared/mbi/content-design.md) -- one growing document uploaded at each checkpoint.
    subtask_id is recorded for context only (which checkpoint triggered this upload).
    """
    # The stored name is {student}_{task}{ext} and only ext comes from the
    # upload, so a crafted filename cannot walk up out of the directory -- '..'
    # can never be the first path component. It can still decide the stored
    # extension though ('1_1.php', a null byte surviving as '.py'), so pin it to
    # the formats we actually accept and fall back to .bin for anything else.
    ext = '.' + file_extension(original_filename)
    if ext[1:] not in config.ALLOWED_EXTENSIONS:
        ext = '.bin'
    upload_dir = _artifact_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    for old in glob.glob(os.path.join(upload_dir, f'{student_id}_{task_id}.*')):
        os.remove(old)
    disk_filename = f'{student_id}_{task_id}{ext}'
    with open(os.path.join(upload_dir, disk_filename), 'wb') as out:
        out.write(file_bytes)
    models.save_student_artifact_file(student_id, task_id, subtask_id, original_filename, disk_filename)


def _unlink_artifact_files(disk_filenames):
    """Remove stored artifact files from disk (call after models.delete_student/delete_all_students_in_klasse)."""
    upload_dir = _artifact_upload_dir()
    for disk_filename in disk_filenames:
        filepath = os.path.join(upload_dir, disk_filename)
        if os.path.exists(filepath):
            os.remove(filepath)


def _unlink_material_files(pfade):
    """Remove stored material files from disk (call after models.delete_task, only for pfade it flagged as unreferenced)."""
    for pfad in pfade:
        filepath = os.path.join(config.UPLOAD_FOLDER, pfad)
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/schueler/thema/<slug>/aufgabe-<int:position>/artefakt/vorschau', methods=['POST'])
@student_required
def student_artifact_preview(slug, position):
    """Step 1: receive upload, extract text, return preview. No LLM, no DB write."""
    student_id = session['student_id']
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        return jsonify({'error': 'Thema nicht gefunden'}), 404

    all_subtasks = models.get_student_subtask_progress(task['id'])
    visible = models.get_visible_subtasks_for_student(student_id, klasse['id'], task['task_id'])
    visible_ids = {s['id'] for s in visible}
    subtasks = [st for st in all_subtasks if st['id'] in visible_ids]
    subtask = _resolve_subtask_by_position(subtasks, position)
    if not subtask:
        return jsonify({'error': 'Aufgabe nicht gefunden'}), 404

    graded = subtask.get('graded_artifact_json')
    if not graded:
        return jsonify({'error': 'Diese Aufgabe hat kein Artefakt-Feedback'}), 400
    graded = json.loads(graded) if isinstance(graded, str) else graded
    allowed_formats = [f.lower() for f in graded.get('format', [])]

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    filename = f.filename
    ext = ('.' + filename.rsplit('.', 1)[-1].lower()) if '.' in filename else ''
    if ext not in artifact_processor.ACCEPTED_FORMATS:
        return jsonify({'error': f'Format {ext} wird nicht unterstützt'}), 400
    if allowed_formats and ext not in allowed_formats:
        return jsonify({'error': f'Erwartet: {", ".join(allowed_formats)}'}), 400

    raw_bytes = f.read()
    format_error = _artifact_format_error(filename, raw_bytes)
    if format_error:
        return jsonify({'error': format_error}), 400
    extract_bytes = artifact_processor.strip_pptx_metadata(raw_bytes) if ext == '.pptx' else raw_bytes

    try:
        extracted = artifact_processor.extract_artifact(extract_bytes, filename)
    except Exception as e:
        return jsonify({'error': f'Datei konnte nicht gelesen werden: {e}'}), 400

    _save_artifact_file(student_id, task['task_id'], subtask['id'], raw_bytes, filename)

    student = models.get_student(student_id)
    full_name = f"{student['vorname']} {student['nachname']}" if student else ''
    # Prepend filename so LLM can check naming criterion; anonymize together
    anonymized = artifact_processor.anonymize(f"[Dateiname: {filename}]\n\n{extracted}", full_name, klasse['name'])

    return jsonify({
        'preview_text': anonymized,
        'filename': filename,
        'subtask_id': subtask['id'],
        'file_saved': True,
        'file_url': url_for('download_student_artifact', student_id=student_id, task_id=task['task_id']),
    })


@app.route('/schueler/thema/<slug>/aufgabe-<int:position>/artefakt/feedback', methods=['POST'])
@student_required
def student_artifact_feedback(slug, position):
    """Step 2: receive anonymized text, call LLM checklist, store and return result."""
    student_id = session['student_id']
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        return jsonify({'error': 'Thema nicht gefunden'}), 404

    all_subtasks = models.get_student_subtask_progress(task['id'])
    visible = models.get_visible_subtasks_for_student(student_id, klasse['id'], task['task_id'])
    visible_ids = {s['id'] for s in visible}
    subtasks = [st for st in all_subtasks if st['id'] in visible_ids]
    subtask = _resolve_subtask_by_position(subtasks, position)
    if not subtask:
        return jsonify({'error': 'Aufgabe nicht gefunden'}), 404

    graded = subtask.get('graded_artifact_json')
    if not graded:
        return jsonify({'error': 'Keine Kriterienliste für diese Aufgabe'}), 400
    graded = json.loads(graded) if isinstance(graded, str) else graded

    student = models.get_student(student_id)
    student_path = (student or {}).get('lernpfad') or 'wanderweg'
    full_name = f"{student['vorname']} {student['nachname']}" if student else ''

    body = request.get_json(silent=True) or {}
    anonymized_text = body.get('text', '').strip()
    filename = body.get('filename', '')
    if not anonymized_text:
        return jsonify({'error': 'Kein Text empfangen'}), 400

    result = _build_level2_feedback(
        student_id, klasse, graded, student_path, filename,
        (student or {}).get('vorname', ''), full_name, anonymized_text
    )
    if result['feedback']:
        models.save_artifact_feedback(student_id, subtask['id'], result['feedback'])

    response = {
        'feedback': result['feedback'],
        'checks_remaining': result['checks_remaining'],
        'llm_disabled': result['llm_disabled'],
        'rate_limited': result['rate_limited'],
    }
    if models.get_effective_transparency_mode(student_id, klasse['id']):
        response['extracted_text'] = anonymized_text
    return jsonify(response)


@app.route('/schueler/thema/<slug>/aufgabe-<int:position>/abgabe-pruefen', methods=['POST'])
@student_required
def student_artifact_gate_check(slug, position):
    """Deterministic gate check on artifact upload. No LLM. Saves result."""
    student_id = session['student_id']
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        return jsonify({'error': 'Thema nicht gefunden'}), 404

    all_subtasks = models.get_student_subtask_progress(task['id'])
    visible = models.get_visible_subtasks_for_student(student_id, klasse['id'], task['task_id'])
    visible_ids = {s['id'] for s in visible}
    subtasks = [st for st in all_subtasks if st['id'] in visible_ids]
    subtask = _resolve_subtask_by_position(subtasks, position)
    if not subtask:
        return jsonify({'error': 'Aufgabe nicht gefunden'}), 404

    gate_raw = subtask.get('artifact_gate_json')
    if not gate_raw:
        return jsonify({'error': 'Keine Abgabe-Prüfung für diese Aufgabe'}), 400
    gate_config = json.loads(gate_raw) if isinstance(gate_raw, str) else gate_raw

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    filename = f.filename
    ext = ('.' + filename.rsplit('.', 1)[-1].lower()) if '.' in filename else ''
    allowed = [fmt.lower() for fmt in gate_config.get('format', [])]
    if allowed and ext not in allowed:
        return jsonify({'error': f'Erwartet: {", ".join(allowed)}'}), 400

    file_bytes = f.read()
    format_error = _artifact_format_error(filename, file_bytes)
    if format_error:
        return jsonify({'error': format_error}), 400
    try:
        result = artifact_checker.check_gate(file_bytes, filename, gate_config,
                                             _template_loader(task['task_id']))
    except Exception as e:
        return jsonify({'error': f'Datei konnte nicht gelesen werden: {e}'}), 400

    # Saved regardless of pass/fail -- "latest submission", not "latest passing submission"
    _save_artifact_file(student_id, task['task_id'], subtask['id'], file_bytes, filename)
    result['file_saved'] = True
    result['file_url'] = url_for('download_student_artifact', student_id=student_id, task_id=task['task_id'])

    # The verdict follows the stored file. _save_artifact_file above keeps the latest
    # upload, not the latest passing one, so a gate that stayed "passed" after a failing
    # re-upload described a file that is no longer there -- the card kept its green
    # "Abgabe geprueft" header above a fresh list of seven errors. One file, one verdict.
    models.save_artifact_gate_result(task['id'], subtask['id'], result['passed'])
    models.log_artifact_gate_attempt(student_id, subtask['id'], result['passed'], result.get('details', []))

    # Inline gate (non-capstone): auto-complete the subtask on pass
    is_capstone = (position == len(subtasks))
    if result['passed'] and not is_capstone:
        toggle_result = models.toggle_student_subtask(task['id'], subtask['id'], True)
        models.log_analytics_event(
            event_type='subtask_complete',
            user_id=student_id,
            user_type='student',
            metadata={'student_task_id': task['id'], 'subtask_id': subtask['id']}
        )
        if not toggle_result.get('quiz_pending') and models.check_task_completion(task['id']):
            models.mark_task_complete(task['id'])
            models.log_analytics_event(
                event_type='task_complete',
                user_id=student_id,
                user_type='student',
                metadata={'student_task_id': task['id']}
            )

    # Filename check is deterministic and always runs on a passed gate; LLM criteria
    # only run when the class has LLM feedback enabled (see _build_level2_feedback).
    # This makes the checkpoint card the single upload point for both checks.
    if result['passed']:
        graded_raw = subtask.get('graded_artifact_json')
        if graded_raw:
            graded = json.loads(graded_raw) if isinstance(graded_raw, str) else graded_raw
            student = models.get_student(student_id)
            full_name = f"{student['vorname']} {student['nachname']}" if student else ''
            student_path = (student or {}).get('lernpfad') or 'wanderweg'

            anonymized = None
            criteria = _get_criteria_for_path(graded, student_path)
            if criteria and klasse.get('llm_artifact_feedback_enabled'):
                try:
                    extract_bytes = artifact_processor.strip_pptx_metadata(file_bytes) if ext == '.pptx' else file_bytes
                    extracted = artifact_processor.extract_artifact(extract_bytes, filename)
                    anonymized = artifact_processor.anonymize(f"[Dateiname: {filename}]\n\n{extracted}", full_name, klasse['name'])
                except Exception as e:
                    print(f"Inline gate LLM feedback error: {type(e).__name__}: {e}", file=sys.stderr)
                    # Extraction failure is non-blocking; gate result stands, filename check still runs below

            level2 = _build_level2_feedback(
                student_id, klasse, graded, student_path, filename,
                (student or {}).get('vorname', ''), full_name, anonymized or ''
            )
            if level2['feedback']:
                models.save_artifact_feedback(student_id, subtask['id'], level2['feedback'])
                result['llm_feedback'] = level2['feedback']
            result['checks_remaining'] = level2['checks_remaining']
            result['filename_checked'] = level2['filename_checked']
            if anonymized and models.get_effective_transparency_mode(student_id, klasse['id']):
                result['extracted_text'] = anonymized

    return jsonify(result)


@app.route('/artefakt-datei/<int:student_id>/<int:task_id>/download')
def download_student_artifact(student_id, task_id):
    """Download the latest artifact upload for a student+task (unit). Owner (student) or admin only."""
    if session.get('student_id') != student_id and 'admin_id' not in session:
        abort(403)
    record = models.get_student_artifact_file(student_id, task_id)
    if not record:
        abort(404)
    upload_dir = _artifact_upload_dir()
    filepath = os.path.join(upload_dir, record['disk_filename'])
    if not os.path.exists(filepath):
        abort(404)
    return send_from_directory(
        upload_dir, record['disk_filename'],
        as_attachment=True, download_name=record['original_filename']
    )


def _get_criteria_for_path(graded_artifact, student_path):
    """Select the best matching criteria array for the student's learning path.

    Cascade: criteria_gipfeltour → criteria_bergweg → criteria (wanderweg baseline).
    Falls back to the next lower path if the specific array is not defined.
    """
    cascade = {
        'gipfeltour': ['criteria_gipfeltour', 'criteria_bergweg', 'criteria'],
        'bergweg':    ['criteria_bergweg', 'criteria'],
        'wanderweg':  ['criteria'],
        'seilbahn':   ['criteria'],
    }
    for key in cascade.get(student_path or 'wanderweg', ['criteria']):
        if graded_artifact.get(key):
            return graded_artifact[key]
    return []


def _build_level2_feedback(student_id, klasse, graded, student_path, filename, vorname, full_name, anonymized_text):
    """Level 2 artifact feedback: filename check is deterministic and always runs;
    LLM criteria only run when the class has LLM feedback enabled and the student
    still has check budget left. Keeping these independent means disabling LLM
    feedback for a class no longer silently disables the (free) filename check too.
    """
    feedback = []
    expected_filename = graded.get('expected_filename')
    filename_checked = bool(expected_filename and filename)
    if filename_checked:
        feedback.append(artifact_checker.check_filename(filename, expected_filename, vorname, full_name))

    llm_enabled = bool(klasse.get('llm_artifact_feedback_enabled'))
    rate_limited = False
    if llm_enabled:
        criteria = _get_criteria_for_path(graded, student_path)
        if criteria:
            if models.get_artifact_checks_remaining(student_id) <= 0:
                rate_limited = True
            elif anonymized_text:
                llm_feedback = llm_grading.grade_artifact_checklist(anonymized_text, criteria)
                feedback.extend(llm_feedback)
                if llm_feedback:
                    models.record_llm_usage(student_id, 'artifact_feedback', 0)

    return {
        'feedback': feedback,
        'llm_disabled': not llm_enabled,
        'rate_limited': rate_limited,
        'checks_remaining': models.get_artifact_checks_remaining(student_id),
        # The client runs its own loose "filename contains the keyword" check as a
        # fallback. Tell it when the exact expected_filename check already ran, so the
        # two do not stack -- they can even disagree (keyword present, exact name wrong).
        'filename_checked': filename_checked,
    }


def _artifact_file_details(unit_artifact_file, subtasks, student, klasse, task_id=None):
    """Re-check the stored artifact against each *earlier* checkpoint's structural gate
    (regression check on the growing document), plus criteria/feedback for the checkpoint
    it was actually last uploaded for.

    The checkpoint it was last uploaded for is reported separately (last_position) and
    excluded from checkpoint_status -- its real state is the criteria/llm_feedback below,
    not a pass/fail dot that would duplicate and contradict that.

    Checkpoint status is always deterministic (no LLM). The criteria/feedback view depends
    on the klasse's LLM-feedback toggle: when on and a persisted result exists for the last
    checkpoint, show that graded checklist; otherwise fall back to the plain criteria list.
    Returns (checkpoint_status: list[{position, passed}], criteria: list[str] | None,
    llm_feedback: list[dict] | None, last_position: int | None).
    """
    if not unit_artifact_file:
        return [], None, None, None

    upload_dir = _artifact_upload_dir()
    filepath = os.path.join(upload_dir, unit_artifact_file['disk_filename'])
    if not os.path.exists(filepath):
        return [], None, None, None

    last_position = next(
        (i + 1 for i, st in enumerate(subtasks) if st['id'] == unit_artifact_file['last_subtask_id']), None
    )
    if not last_position:
        return [], None, None, None

    with open(filepath, 'rb') as f:
        stored_bytes = f.read()

    checkpoint_status = []
    for i, st in enumerate(subtasks[:last_position - 1]):
        gate_raw = st.get('artifact_gate_json')
        if not gate_raw:
            continue
        try:
            gate_config = json.loads(gate_raw)
            check = artifact_checker.check_gate(stored_bytes, unit_artifact_file['original_filename'],
                                                gate_config, _template_loader(task_id))
            checkpoint_status.append({'position': i + 1, 'passed': check['passed']})
        except (json.JSONDecodeError, TypeError):
            pass

    criteria = None
    last_subtask = subtasks[last_position - 1]
    if last_subtask.get('graded_artifact_json'):
        try:
            ga = json.loads(last_subtask['graded_artifact_json'])
            student_path = (student or {}).get('lernpfad') or 'wanderweg'
            criteria = _get_criteria_for_path(ga, student_path) or None
        except (json.JSONDecodeError, TypeError):
            pass

    llm_feedback = None
    if klasse.get('llm_artifact_feedback_enabled'):
        fb = models.get_artifact_feedback((student or {}).get('id'), last_subtask['id'])
        llm_feedback = fb['feedback'] if fb else None

    return checkpoint_status, criteria, llm_feedback, last_position


def _handle_quiz(student_id, student, task, slug, quiz_json_str, subtask_id=None, position=None):
    """Shared quiz logic for topic and subtask quizzes."""
    student_task_id = task['id']
    quiz = _filter_quiz_for_path(json.loads(quiz_json_str), student)

    # Filter out short_answer (LLM-required) if rate limit exceeded. Must run
    # before the POST/GET split so grading indices always match what was
    # displayed - fill_blank is kept, it grades via exact match with LLM only
    # as fallback.
    llm_available = models.check_llm_rate_limit(student_id)
    if not llm_available:
        quiz['questions'] = [q for q in quiz['questions'] if q.get('type', 'multiple_choice') != 'short_answer']

    # Guard against a quiz left with no questions for this student (all
    # path-restricted away, or all short_answer while rate-limited).
    if not quiz['questions']:
        flash('Für dich sind aktuell keine Fragen in diesem Quiz verfügbar. Versuche es später erneut.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    if request.method == 'POST':
        # Grade the quiz using the mapping from hidden fields
        punkte = 0
        antworten = {}

        question_order = json.loads(request.form.get('question_order', '[]'))
        max_punkte = len(question_order) if question_order else len(quiz['questions'])

        for shuffled_idx in range(max_punkte):
            original_q_idx = question_order[shuffled_idx] if question_order else shuffled_idx
            question = quiz['questions'][original_q_idx]
            qtype = question.get('type', 'multiple_choice')

            if qtype == 'fill_blank':
                student_text = request.form.get(f'q{shuffled_idx}', '').strip()
                if not student_text:
                    antworten[str(original_q_idx)] = {"text": "", "correct": False, "feedback": "Keine Antwort.", "source": "empty"}
                elif student_text.lower() in [a.lower() for a in question['answers']]:
                    punkte += 1
                    antworten[str(original_q_idx)] = {"text": student_text, "correct": True, "feedback": "Richtig!", "source": "match"}
                else:
                    result = llm_grading.grade_answer(question['text'], ', '.join(question['answers']), student_text, student_id)
                    if result['correct']:
                        punkte += 1
                    antworten[str(original_q_idx)] = {"text": student_text, **result}

            elif qtype == 'short_answer':
                student_text = request.form.get(f'q{shuffled_idx}', '').strip()
                if not student_text:
                    antworten[str(original_q_idx)] = {"text": "", "correct": False, "feedback": "Keine Antwort.", "source": "empty"}
                else:
                    result = llm_grading.grade_answer(question['text'], question['rubric'], student_text, student_id)
                    if result['correct']:
                        punkte += 1
                    antworten[str(original_q_idx)] = {"text": student_text, **result}

            elif quiz_grading.is_interactive(qtype):
                # The field carries JSON written by quiz_interactive.js: an array of
                # item texts for ordering, a {links: rechts} object for matching.
                # Text, not indices -- see quiz_grading's module docstring.
                try:
                    submitted = json.loads(request.form.get(f'q{shuffled_idx}', 'null'))
                except json.JSONDecodeError:
                    submitted = None
                result = quiz_grading.grade(question, submitted)
                punkte += result['points']
                antworten[str(original_q_idx)] = {
                    'type': qtype,
                    'answer': submitted,
                    'text': quiz_grading.answer_text(question, submitted),
                    'correct': result['correct'],
                    'points': result['points'],
                    'right': result['right'],
                    'total': result['total'],
                    'feedback': result['feedback'],
                    'source': 'interactive',
                }

            else:
                # Multiple choice (default)
                answer_map = json.loads(request.form.get(f'answer_map_{shuffled_idx}', '[]'))
                submitted = request.form.getlist(f'q{shuffled_idx}')
                submitted_shuffled = [int(x) for x in submitted]
                submitted_original = [answer_map[i] for i in submitted_shuffled] if answer_map else submitted_shuffled
                correct = question['correct']
                antworten[str(original_q_idx)] = submitted_original
                if set(submitted_original) == set(correct):
                    punkte += 1

        if question_order:
            antworten['_question_order'] = question_order
        # ordering/matching can score half a point (quiz_grading.points_for), so
        # punkte is no longer necessarily an integer. Drop the ".0" when it is one
        # so a quiz without those types stores exactly what it always stored.
        punkte = int(punkte) if punkte == int(punkte) else punkte
        attempt_id, bestanden = models.save_quiz_attempt(
            student_task_id, punkte, max_punkte, json.dumps(antworten),
            subtask_id=subtask_id, quiz_snapshot=quiz_json_str
        )

        llm_answers = [v for v in antworten.values() if isinstance(v, dict) and v.get('source') == 'llm']
        analytics_meta = {
            'student_task_id': student_task_id,
            'subtask_id': subtask_id,
            'punkte': punkte,
            'max_punkte': max_punkte,
            'bestanden': bestanden,
            'prozent': int((punkte / max_punkte) * 100) if max_punkte > 0 else 0
        }
        if llm_answers:
            analytics_meta['llm_provider'] = llm_answers[0].get('llm_provider', config.LLM_PROVIDER)
            analytics_meta['llm_model'] = llm_answers[0].get('llm_model', config.LLM_MODEL)
            analytics_meta['llm_graded_count'] = len(llm_answers)
        models.log_analytics_event(
            event_type='quiz_attempt',
            user_id=student_id,
            user_type='student',
            metadata=analytics_meta
        )

        if subtask_id and bestanden:
            models.advance_to_next_subtask(student_task_id, subtask_id)

        if models.check_task_completion(student_task_id):
            models.mark_task_complete(student_task_id)
            models.log_analytics_event(
                event_type='task_complete',
                user_id=student_id,
                user_type='student',
                metadata={'student_task_id': student_task_id}
            )

        if subtask_id and position:
            return redirect(url_for('student_quiz_result_subtask', slug=slug, position=position))
        return redirect(url_for('student_quiz_result', slug=slug))

    # Shuffle questions and answers for display
    import random as quiz_random

    question_order = list(range(len(quiz['questions'])))
    quiz_random.shuffle(question_order)

    shuffled_questions = []
    answer_maps = []

    for original_idx in question_order:
        q = quiz['questions'][original_idx]
        qtype = q.get('type', 'multiple_choice')

        if qtype in ('fill_blank', 'short_answer'):
            answer_maps.append([])
            shuffled_q = {
                'question': q['text'],
                'answers': [],
                'correct': [],
                'image': q.get('image'),
                'type': qtype
            }
        elif quiz_grading.is_interactive(qtype):
            answer_maps.append([])
            shuffled_q = {
                'question': q['text'],
                'answers': [],
                'correct': [],
                'image': q.get('image'),
                'type': qtype,
                # Shuffled pieces only, no key -- the template hands this straight
                # to quiz_interactive.js.
                'interactive': quiz_grading.presentation(q, quiz_random),
            }
        else:
            options = q['options']
            answer_order = list(range(len(options)))
            quiz_random.shuffle(answer_order)
            answer_maps.append(answer_order)
            shuffled_q = {
                'question': q['text'],
                'answers': [options[i] for i in answer_order],
                'correct': q['correct'],
                'image': q.get('image'),
                'type': 'multiple_choice'
            }
        shuffled_questions.append(shuffled_q)

    shuffled_quiz = {'questions': shuffled_questions}

    return render_template('student/quiz.html',
                           student=student,
                           task=task,
                           quiz=shuffled_quiz,
                           question_order=json.dumps(question_order),
                           answer_maps=[json.dumps(m) for m in answer_maps],
                           slug=slug,
                           position=position)


@app.route('/schueler/thema/<slug>/quiz', methods=['GET', 'POST'])
@student_required
def student_quiz(slug):
    student_id = session['student_id']
    student = models.get_student(student_id)

    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    if not task['quiz_json']:
        flash('Dieses Thema hat kein Quiz.', 'warning')
        return redirect(url_for('student_dashboard'))

    return _handle_quiz(student_id, student, task, slug, task['quiz_json'])


@app.route('/schueler/thema/<slug>/aufgabe-<int:position>/quiz', methods=['GET', 'POST'])
@student_required
def student_quiz_subtask(slug, position):
    student_id = session['student_id']
    student = models.get_student(student_id)

    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Resolve subtask by position
    all_subtasks = models.get_student_subtask_progress(task['id'])
    visible_subtask_ids = [s['id'] for s in models.get_visible_subtasks_for_student(
        student_id, klasse['id'], task['task_id']
    )]
    subtasks = [st for st in all_subtasks if st['id'] in visible_subtask_ids]
    subtask = _resolve_subtask_by_position(subtasks, position)

    if not subtask:
        flash('Aufgabe nicht gefunden.', 'danger')
        return redirect(url_for('student_klasse', slug=slug))

    with models.db_session() as conn:
        subtask_row = conn.execute(
            "SELECT quiz_json FROM subtask WHERE id = ?", (subtask['id'],)
        ).fetchone()

    if not subtask_row or not subtask_row['quiz_json']:
        flash('Diese Aufgabe hat kein Quiz.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    if subtask.get('checkpoint_type') == 'quiz':
        if not _school_gate_ok(subtask):
            flash('Dieser Checkpoint ist nur im Schulnetzwerk verfügbar.', 'warning')
            return redirect(url_for('student_klasse', slug=slug))
        return _handle_checkpoint_quiz(student, task, slug, subtask, position, klasse)

    return _handle_quiz(student_id, student, task, slug, subtask_row['quiz_json'],
                        subtask_id=subtask['id'], position=position)


# ============ Chemie Quiz-Checkpoint (Checkpoint-Punktekonto) ============
# One Quiz-checkpoint = one immediate-retry session (like warmup), not the
# single-submit pass/fail@70% flow _handle_quiz uses. Scoring is 0/2/3, logged
# to checkpoint_attempt instead of quiz_attempt. See
# docs/shared/lernmanager/chemie-data-contract.md §3-4.

def _serialize_checkpoint_question(q, index):
    """Question payload for the client. Same visibility rule as warmup
    (_serialize_question_for_js): MC options go to the client, fill_blank
    answers don't. Never include 'correct' - unlike warmup this is a
    retry-until-correct session, so leaking the answer up front (or on a
    wrong attempt) would break the 3-vs-2 scoring signal.

    `index` is the question's position in the stored quiz_json, which is what every
    route validates against -- not its position in the list the client was handed.
    The two diverge whenever the rendered list is a subset: short_answer questions
    are dropped when the LLM budget is spent, and a retry session shows only the
    questions whose flag was rejected. The client sends this value back, never its
    own array position."""
    qtype = q.get('type', 'multiple_choice')
    result = {'type': qtype, 'text': q['text'], 'index': index}
    if quiz_grading.is_interactive(qtype):
        result.update(quiz_grading.presentation(q))
    elif qtype not in ('fill_blank', 'short_answer'):
        result['options'] = q.get('options', [])
    if q.get('image'):
        result['image'] = q['image']
    return result


def _resolve_checkpoint_subtask(student_id, slug, subtask_id):
    """Resolve + authorize a Quiz-checkpoint subtask for the current student.
    Returns (task, subtask_dict) or (None, None). `task` is the student_task row."""
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        return None, None
    with models.db_session() as conn:
        row = conn.execute(
            "SELECT * FROM subtask WHERE id = ? AND task_id = ? AND checkpoint_type = 'quiz'",
            (subtask_id, task['task_id'])
        ).fetchone()
    if not row:
        return None, None
    subtask = dict(row)
    if not _school_gate_ok(subtask):
        return None, None
    return task, subtask


def _checkpoint_progress(subtask_id):
    """Server-side attempt/hint/solved counters for one in-progress checkpoint
    session. Kept server-side, never trusted from the client, since these
    numbers feed the 0/2/3 score directly.

    session_uid: a short id (not the answer text itself, safe for the session
    cookie) correlating this session's checkpoint_answer rows so they can be
    stamped with the real checkpoint_attempt_id once the session finishes --
    see create_checkpoint_answer/create_checkpoint_attempt."""
    all_progress = session.get('checkpoint_progress', {})
    progress = all_progress.get(str(subtask_id)) or {
        'attempts': {}, 'hints_used': {}, 'solved': {}, 'gave_up': {}, 'llm_errors': {},
        'flagged': {}
    }
    # setdefault, not part of the literal above: a session already in progress when
    # flags shipped must not KeyError on its first report.
    progress.setdefault('flagged', {})
    # setdefault, not unconditional -- a session already in progress when this
    # field was introduced must keep the uid it was first given, not get a new
    # one on every request.
    progress.setdefault('session_uid', uuid.uuid4().hex)
    return progress


def _has_live_checkpoint_progress(subtask_id):
    """Whether this browser session already holds progress for this checkpoint.

    The resume path (_resume_checkpoint_progress) may only run when it does not:
    the cookie is the newer record of the two while a sitting is live, and it holds
    the one thing the log cannot give back -- hints taken since the last answer.
    """
    return session.get('checkpoint_progress', {}).get(str(subtask_id)) is not None


def _resume_checkpoint_progress(student_id, subtask_id, progress):
    """Fill an empty progress dict from the answer log, if there is a sitting to
    resume. Returns the set of question indices that are already finished
    (solved, given up or reported), empty when there is nothing to resume."""
    resumed = models.resume_unfinished_checkpoint_session(student_id, subtask_id)
    if not resumed:
        return set()

    progress['session_uid'] = resumed['session_uid']
    done = set()
    for index, state in resumed['questions'].items():
        qidx = str(index)
        progress['attempts'][qidx] = state['attempts']
        progress['hints_used'][qidx] = state['hints_used']
        if state['solved']:
            progress['solved'][qidx] = True
        if state['gave_up']:
            progress['gave_up'][qidx] = True
        if state['flagged']:
            progress['flagged'][qidx] = True
        if state['llm_errors']:
            progress.setdefault('llm_errors', {})[qidx] = state['llm_errors']
        if state['solved'] or state['gave_up'] or state['flagged']:
            done.add(index)
    return done


def _save_checkpoint_progress(subtask_id, progress):
    all_progress = session.get('checkpoint_progress', {})
    all_progress[str(subtask_id)] = progress
    session['checkpoint_progress'] = all_progress


def _clear_checkpoint_progress(subtask_id):
    all_progress = session.get('checkpoint_progress', {})
    all_progress.pop(str(subtask_id), None)
    session['checkpoint_progress'] = all_progress


def _score_checkpoint_session(question_results):
    """0/2/3 score for one completed Quiz-checkpoint session, per
    docs/shared/lernmanager/chemie-data-contract.md §3a: per-question score
    (3 = first try, no hint; 2 = correct via hint and/or retry; 0 = never
    solved) consolidated across the checkpoint via min(), not an average -
    score stays a strict three-value category, matching the Kern-Sperre gate's
    `score >= 2` ("every required question was eventually solved").

    A flagged question carries no score and is left out of the min() -- decided
    2026-08-31, the optimistic reading. The student reported it as broken and moved
    on, so holding the whole session at 0 until a teacher rules would recreate exactly
    the stuck-ness the report exists to remove. The consequence is that the number is
    PROVISIONAL while any flag on the attempt is still open: `score >= 2` no longer
    proves every question was solved, only every question that still counts. Nothing
    downstream may treat such an attempt as final -- see checkpoint_score_is_provisional().

    A session where every question was flagged scores 0: there is nothing to take a
    min() over, and 0 is the honest floor to hold until the teacher has ruled.

    question_results: list of dicts, one per question in this checkpoint's quiz:
    {'solved': bool, 'gave_up': bool, 'flagged': bool, 'attempts': int, 'hints_used': int}
    """
    scores = [s for s in _checkpoint_question_scores(question_results) if s is not None]
    return min(scores) if scores else 0


def _checkpoint_question_scores(question_results):
    """Per-question 0/2/3 score list, same classification `_score_checkpoint_session`
    consolidates via min() -- factored out so the completion-screen reason text
    (`_checkpoint_score_reason`) can break the session score down by question
    without re-deriving the 0/2/3 rule a second time.

    None at a position = the question was flagged as broken and has no score yet.
    Stored as-is in checkpoint_attempt.question_scores_json, which is what lets one
    question be rescored later without rebuilding the whole session."""
    def question_score(result):
        if result.get('flagged'):
            return None
        if not result['solved']:
            return 0
        if result['attempts'] > 1 or result['hints_used'] > 0:
            return 2
        if result.get('retry_after_rejected_flag'):
            # A question redone after a REJECTED report cannot score 3 even if solved
            # cleanly: the student had a second look at it with the clock stopped,
            # which is exactly what a retry or a hint costs. Without this, reporting a
            # question is a free think-break and the report becomes the cheapest move
            # on a hard question.
            return REJECTED_FLAG_RETRY_CAP
        return 3

    return [question_score(result) for result in question_results]


# See the retry_after_rejected_flag branch above. Confirmed by Chemie on 2026-09-01,
# after the question this number was waiting on was settled a level up: their grade
# now averages over QUESTIONS rather than over consolidated checkpoint scores, so a
# capped redo is one question of N and not, as under min(), a cap on the whole
# checkpoint. min() itself is unchanged and now feeds only the Kern-Sperre.
REJECTED_FLAG_RETRY_CAP = 2


def _checkpoint_score_reason(question_results):
    """Short German reason line for the completion screen, per chemie's agreed
    Option 1 (`chemie-checkpoint-status.md` §1: show score + short reason, nothing
    live during the session)."""
    scores = _checkpoint_question_scores(question_results)
    total = len(scores)
    flagged = sum(1 for s in scores if s is None)
    unsolved = sum(1 for s in scores if s == 0)
    first_try = sum(1 for s in scores if s == 3)

    # The flagged part comes first and is stated separately: it is the one part of
    # the number the student cannot influence and a teacher still has to rule on.
    flagged_note = ''
    if flagged:
        counted = total - flagged
        flagged_note = (f'{flagged} von {total} Fragen hast du gemeldet — '
                        f'die zählen hier noch nicht mit. ')
        if not counted:
            return flagged_note + 'Deine Lehrkraft schaut sich den Checkpoint an.'
        total = counted

    if unsolved:
        return flagged_note + f'{unsolved} von {total} Fragen wurden nicht gelöst.'
    if first_try == total:
        return flagged_note + 'Alle Fragen im ersten Versuch ohne Tipp richtig beantwortet.'
    if first_try == 0:
        return flagged_note + 'Alle Fragen gelöst, aber mit Tipp oder mehreren Versuchen.'
    return (flagged_note + f'{first_try} von {total} Fragen im ersten Versuch richtig, '
            'der Rest mit Tipp oder mehreren Versuchen.')


def _handle_checkpoint_quiz(student, task, slug, subtask, position, klasse):
    """GET: render a Chemie Quiz-checkpoint as an immediate-retry session."""
    quiz = json.loads(subtask['quiz_json'])
    llm_available = models.check_llm_rate_limit(student['id'], usage_tag='checkpoint_quiz')
    questions = [(i, q) for i, q in enumerate(quiz.get('questions', []))
                 if llm_available or q.get('type', 'multiple_choice') != 'short_answer']

    # A rejected report puts exactly those questions back in front of the student,
    # and nothing else. Not a second sitting: the existing attempt is rescored on
    # finish, so the Aufgabe is not re-ticked and no second checkpoint_attempt
    # appears. Only meaningful while that attempt is still the live one -- after a
    # teacher reset there is nothing to rescore, so the checkpoint is simply taken
    # again from the top and the reports are closed on the way out.
    standing_attempt = models.get_latest_checkpoint_attempt(student['id'], subtask['id'])
    retry_flags = (models.get_flags_for_retry(student['id'], subtask['id'])
                   if standing_attempt else [])
    retry_indices = {f['question_index'] for f in retry_flags}
    if retry_indices:
        questions = [(i, q) for i, q in questions if i in retry_indices]

    if not questions:
        flash('Für diesen Checkpoint sind aktuell keine Fragen verfügbar. Versuche es später erneut.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    hints = json.loads(subtask['checkpoint_hints_json']) if subtask.get('checkpoint_hints_json') else []

    progress = _checkpoint_progress(subtask['id'])
    # Entering or leaving retry mode starts a clean session: the two score
    # different things, and carrying counters across would let a solved question
    # from the first sitting count as solved in the redo.
    if bool(retry_indices) != bool(progress.get('retry')):
        _clear_checkpoint_progress(subtask['id'])
        progress = _checkpoint_progress(subtask['id'])

    # A sitting that ran out of lesson (or lost its cookie to a school PC wiping
    # browser data at logout) picks up where it stopped, instead of making the
    # student redo questions they already solved -- Chemie's requirement of
    # 2026-09-01, and the reason a checkpoint's hardness is completeness, not time.
    # Only when the cookie is empty: a live sitting is the newer record.
    done = (set() if _has_live_checkpoint_progress(subtask['id'])
            else _resume_checkpoint_progress(student['id'], subtask['id'], progress))
    progress['retry'] = bool(retry_indices)
    progress['retry_flag_ids'] = [f['id'] for f in retry_flags]
    # Which of the redone questions may not score 3. Per question, not per session:
    # one sitting can mix a rejected report (capped, the student reported a working
    # question) with a question we sent back ourselves (uncapped, our bug).
    progress['retry_capped'] = [f['question_index'] for f in retry_flags
                                if f['status'] == 'abgelehnt']

    # `finish` scores exactly `rendered`, so it must cover the whole sitting --
    # including questions finished before the interruption, which are not shown
    # again. The union matters when the LLM budget is spent on the day of the
    # resume: a short_answer solved earlier is dropped from `questions` but still
    # has to be scored, while an unsolved one stays out or finish would wait
    # forever for an answer the student was never shown.
    progress['rendered'] = sorted({i for i, _ in questions} | done)
    _save_checkpoint_progress(subtask['id'], progress)

    # Only what is still open goes on screen. The banner carries the rest -- without
    # it, coming back to 3 of 7 questions looks like the checkpoint shrank.
    open_questions = [(i, q) for i, q in questions if i not in done]
    resume = ({'done': len(done), 'total': len(progress['rendered'])} if done else None)

    # enumerate over the STORED quiz, then filter -- so each question keeps the index
    # every route validates against even when the rendered list is a subset.
    questions_json = json.dumps([_serialize_checkpoint_question(q, i) for i, q in open_questions])
    transparency_mode = models.get_effective_transparency_mode(student['id'], klasse['id'] if klasse else None)

    # A student who already finished this checkpoint sees the standing result and
    # whether a teacher has checked it (migrate_049). Without this the review was
    # invisible to them: the score appeared once on the completion screen and there
    # was nowhere to look afterwards.
    last_attempt = standing_attempt
    review = None
    reopened = None
    if last_attempt:
        review = {
            'status': models.checkpoint_review_status(last_attempt),
            'score': models.effective_checkpoint_score(last_attempt),
            'llm_score': last_attempt['score'],
            'feedback': last_attempt.get('student_feedback'),
            # A score with a reported question still open is not the final number --
            # saying so here is the only place the student would ever find out.
            'provisional': models.checkpoint_score_is_provisional(last_attempt),
        }
    else:
        # No live session, but there may be a superseded one -- a reset. Saying so
        # is the whole point: the teacher writes the Rueckmeldung, resets, and the
        # student reads it here on the way into the retake. The else is what keeps
        # it from lingering: once they retake, `review` above takes over.
        reopened = models.get_reopened_checkpoint_notice(student['id'], subtask['id'])

    return render_template('student/checkpoint_quiz.html',
                           student=student, task=task, slug=slug, position=position,
                           subtask_id=subtask['id'], questions_json=questions_json,
                           has_hints=bool(hints), transparency_mode=transparency_mode,
                           review=review, reopened=reopened, resume=resume,
                           flag_reasons=models.CHECKPOINT_FLAG_REASONS,
                           retry_flags=retry_flags,
                           llm_enabled=config.LLM_ENABLED)


@app.route('/schueler/checkpoint/antwort', methods=['POST'])
@student_required
def student_checkpoint_answer():
    """AJAX: grade one attempt within a checkpoint session. Returns correct/
    incorrect only, never the answer itself - the student can retry, and
    revealing it would break the retry-until-correct mechanic."""
    student_id = session['student_id']
    data = request.get_json() or {}
    task, subtask = _resolve_checkpoint_subtask(student_id, data.get('slug'), data.get('subtask_id'))
    if not subtask:
        return jsonify({'error': 'Not found'}), 404

    questions = json.loads(subtask['quiz_json']).get('questions', [])
    question_index = data.get('question_index')
    if question_index is None or not (0 <= question_index < len(questions)):
        return jsonify({'error': 'Invalid question'}), 400

    question = questions[question_index]
    answer = data.get('answer')
    qtype = question.get('type', 'multiple_choice')
    if qtype in ('fill_blank', 'short_answer'):
        is_empty = not (answer or '').strip()
    elif qtype == 'ordering':
        # An ordering question always carries an order -- the shuffled one counts
        # as an answer. There is nothing the student could leave blank.
        is_empty = not isinstance(answer, list) or not answer
    elif qtype == 'matching':
        is_empty = not isinstance(answer, dict) or not answer
    else:
        is_empty = not answer
    if is_empty:
        # Reject before touching progress -- an accidental empty submit must never
        # burn an attempt against the 3-vs-2 scoring rule (chemie-data-contract.md §3a).
        return jsonify({'error': 'empty', 'message': 'Bitte gib eine Antwort ein, bevor du prüfst.'}), 400

    subtask_id = subtask['id']
    qidx = str(question_index)
    progress = _checkpoint_progress(subtask_id)

    # Already solved -> answer idempotently, without grading again and without
    # touching attempts. A second graded call on a solved question costs the student
    # a point (3 requires attempts == 1, see _checkpoint_question_scores) and spends
    # LLM budget for nothing.
    #
    # Scope, honestly: this catches every *sequential* duplicate -- a stale tab, a
    # browser-back resubmit, a retry fired after the first response arrived. It does
    # NOT catch two genuinely simultaneous in-flight requests: checkpoint progress
    # lives in the (cookie-based) Flask session, so both would carry the same
    # pre-click state and neither can see the other. The real guard against the
    # double-click race is client-side (llm_button.js disables the button for the
    # whole round trip); this is the backstop for when that guard is bypassed, and
    # the review UI repairs whatever slipped through historically.
    if progress['solved'].get(qidx):
        return jsonify({'correct': True, 'attempts': progress['attempts'].get(qidx, 1),
                        'duplicate': True})

    if progress['flagged'].get(qidx):
        return jsonify({'error': 'flagged', 'message': CHECKPOINT_FLAGGED_LOCK_MESSAGE}), 403

    # MC answers arrive as a list of indices and matching answers as an object, not as
    # text -- store those as JSON so the log is unambiguous either way (see
    # get_checkpoint_answers_for_attempt). str() on a dict would write a Python repr
    # into the review UI and both exports.
    #
    # Computed here rather than after grading: the unchanged-answer guard below
    # compares against the logged text, so both must be the same string by
    # construction, not by two matching expressions.
    answer_text = (json.dumps(answer, ensure_ascii=False)
                   if isinstance(answer, (list, dict)) else str(answer))

    # Unchanged text -> hand back the previous verdict, grade nothing, count nothing.
    #
    # The guard above only covers a SOLVED question. Resubmitting an unchanged WRONG
    # answer fell through it and was regraded every time: on 2026-09-02 that was 47 of
    # the day's resubmissions (17 within 15s, 30 later). It costs no points -- the
    # score ladder is 3 -> 2 -> 2 -> 2, so the first wrong attempt already did the
    # damage -- but it spends an LLM call per click and puts a duplicate row in front
    # of the teacher.
    #
    # Exact match after normalising, deliberately NOT the fuzzy 0.95 rule
    # _is_duplicate_submission uses to *detect* double-clicks after the fact. That rule
    # is safe only because it also requires both verdicts to agree, which cannot be
    # known before grading; applied here it would swallow a genuine typo fix that flips
    # the verdict ("Neutron" -> "Neutronen"). A miss just means we grade again, as
    # before; a false positive would deny a real retry.
    #
    # No time window either: identical text is pointless to regrade at 1 second or at
    # 5 minutes, and the >15s bucket was the larger half.
    #
    # `correct is None` disables the guard on purpose. That row is either an LLM
    # failure -- whose own error message tells the student "Versuch es gleich nochmal",
    # so resending the same text is the retry we asked for, not a duplicate -- or a
    # 'flagged' row written by student_checkpoint_flag, which is a report and never an
    # answer to compare against. Checked here rather than filtered out in the query:
    # skipping such a row would compare against an older one instead, and could then
    # suppress exactly the retry the error invited.
    previous = models.get_last_checkpoint_answer(progress['session_uid'], question_index)
    if previous and previous['correct'] is not None and \
            _normalized_answer_text(previous) == _normalized_answer_text(
                {'answer_text': answer_text}):
        # bool(), not the raw column: SQLite hands back 0/1, and this route's other
        # paths return real booleans. One endpoint must not answer `false` on one path
        # and `0` on another -- JS treats them alike, a strict comparison downstream
        # does not. Safe here because correct is None was already excluded above.
        return jsonify({'correct': bool(previous['correct']), 'feedback': previous['feedback'],
                        'attempts': progress['attempts'].get(qidx, 1),
                        'unchanged': True})

    # Checkpoint grading is graded (feeds a real school grade), so it must never
    # silently fall back to "assume correct" like warmup does on an LLM outage --
    # strict=True surfaces failure as correct=None instead.
    correct, feedback, source, prompt_version, confidence = _grade_warmup_answer(
        question, answer, usage_tag='checkpoint_quiz', strict=True
    )

    llm_model = config.LLM_MODEL if source in ('llm', 'fallback', 'error') else None

    if correct is None:
        progress.setdefault('llm_errors', {})
        progress['llm_errors'][qidx] = progress['llm_errors'].get(qidx, 0) + 1
        _save_checkpoint_progress(subtask_id, progress)
        models.create_checkpoint_answer(
            student_id, subtask_id, progress['session_uid'], question_index,
            attempt_no=progress['attempts'].get(qidx, 0) + 1, answer_text=answer_text,
            correct=None, feedback=feedback, grader=source, llm_model=llm_model,
            hints_used_before=progress['hints_used'].get(qidx, 0),
            prompt_version=prompt_version, judgment_confidence=confidence
        )
        return jsonify({
            'error': 'llm_unavailable',
            'message': ('Bewertung aktuell nicht möglich. Versuch es gleich nochmal — '
                        'falls es weiter nicht klappt, nutze „Ich weiß es nicht“, '
                        'deine Lehrkraft prüft die Antwort dann von Hand.')
        }), 503

    progress['attempts'][qidx] = progress['attempts'].get(qidx, 0) + 1
    if correct:
        progress['solved'][qidx] = True
    _save_checkpoint_progress(subtask_id, progress)
    models.create_checkpoint_answer(
        student_id, subtask_id, progress['session_uid'], question_index,
        attempt_no=progress['attempts'][qidx], answer_text=answer_text,
        correct=correct, feedback=feedback, grader=source, llm_model=llm_model,
        hints_used_before=progress['hints_used'].get(qidx, 0),
        prompt_version=prompt_version, judgment_confidence=confidence
    )

    return jsonify({'correct': correct, 'attempts': progress['attempts'][qidx]})


@app.route('/schueler/checkpoint/hinweis', methods=['POST'])
@student_required
def student_checkpoint_hint():
    """AJAX: reveal the next escalating hint. Gated to after the first attempt
    (data contract §4) so the button can't be clicked reflexively and corrupt
    the 3-vs-2 scoring signal."""
    student_id = session['student_id']
    data = request.get_json() or {}
    task, subtask = _resolve_checkpoint_subtask(student_id, data.get('slug'), data.get('subtask_id'))
    if not subtask:
        return jsonify({'error': 'Not found'}), 404

    subtask_id = subtask['id']
    qidx = str(data.get('question_index'))
    progress = _checkpoint_progress(subtask_id)
    if progress['flagged'].get(qidx):
        return jsonify({'error': 'flagged', 'message': CHECKPOINT_FLAGGED_LOCK_MESSAGE}), 403
    if progress['attempts'].get(qidx, 0) < 1:
        return jsonify({'error': 'Erst nach dem ersten Versuch verfügbar.'}), 403

    hints = json.loads(subtask['checkpoint_hints_json']) if subtask.get('checkpoint_hints_json') else []
    hint_index = progress['hints_used'].get(qidx, 0)
    if hint_index >= len(hints):
        return jsonify({'hint': None})

    progress['hints_used'][qidx] = hint_index + 1
    _save_checkpoint_progress(subtask_id, progress)
    return jsonify({'hint': hints[hint_index], 'hints_remaining': len(hints) - hint_index - 1})


@app.route('/schueler/checkpoint/aufgeben', methods=['POST'])
@student_required
def student_checkpoint_give_up():
    """AJAX: reveal the correct answer and end retries for one question."""
    student_id = session['student_id']
    data = request.get_json() or {}
    task, subtask = _resolve_checkpoint_subtask(student_id, data.get('slug'), data.get('subtask_id'))
    if not subtask:
        return jsonify({'error': 'Not found'}), 404

    questions = json.loads(subtask['quiz_json']).get('questions', [])
    question_index = data.get('question_index')
    if question_index is None or not (0 <= question_index < len(questions)):
        return jsonify({'error': 'Invalid question'}), 400
    question = questions[question_index]

    qtype = question.get('type', 'multiple_choice')
    if quiz_grading.is_interactive(qtype):
        correct_answer = quiz_grading.correct_answer_text(question)
    elif qtype == 'fill_blank':
        correct_answer = question['answers'][0] if question.get('answers') else ''
    elif qtype == 'short_answer':
        correct_answer = question.get('rubric', '')
    else:
        options = question.get('options', [])
        correct_set = set(question.get('correct', []))
        texts = [opt['text'] if isinstance(opt, dict) else str(opt)
                 for idx, opt in enumerate(options) if idx in correct_set]
        correct_answer = ', '.join(texts)

    subtask_id = subtask['id']
    qidx = str(question_index)
    progress = _checkpoint_progress(subtask_id)
    if progress['flagged'].get(qidx):
        # A reported question must not reveal its answer: the student still owes it
        # if the teacher rejects the report, and giving up here would hand over the
        # solution for free.
        return jsonify({'error': 'flagged', 'message': CHECKPOINT_FLAGGED_LOCK_MESSAGE}), 403
    progress['gave_up'][qidx] = True
    _save_checkpoint_progress(subtask_id, progress)
    models.create_checkpoint_answer(
        student_id, subtask_id, progress['session_uid'], question_index,
        attempt_no=progress['attempts'].get(qidx, 0) + 1, answer_text=None,
        correct=False, feedback=correct_answer, grader='gaveup',
        hints_used_before=progress['hints_used'].get(qidx, 0), gave_up=True
    )

    return jsonify({'correct_answer': correct_answer})


# Every route that could still change a reported question says the same thing --
# one sentence, one place, so "gemeldet" cannot come to mean three different things.
CHECKPOINT_FLAGGED_LOCK_MESSAGE = ('Diese Frage hast du gemeldet. Deine Lehrkraft '
                                   'schaut sie sich an — du kannst hier weitermachen.')


@app.route('/schueler/checkpoint/melden', methods=['POST'])
@student_required
def student_checkpoint_flag():
    """AJAX: report one checkpoint question as broken and move on.

    Deliberately not a give-up: nothing is graded (no LLM call), the correct answer
    is NOT revealed, and the question carries no score until a teacher has ruled on
    the report -- if the report is rejected, the student still owes the question.
    Whatever was already typed is logged as information (correct = NULL,
    grader='flagged'), because it is the best evidence for whether the question or
    its grading was at fault.
    """
    student_id = session['student_id']
    data = request.get_json() or {}
    task, subtask = _resolve_checkpoint_subtask(student_id, data.get('slug'), data.get('subtask_id'))
    if not subtask:
        return jsonify({'error': 'Not found'}), 404

    questions = json.loads(subtask['quiz_json']).get('questions', [])
    question_index = data.get('question_index')
    if question_index is None or not (0 <= question_index < len(questions)):
        return jsonify({'error': 'Invalid question'}), 400
    question = questions[question_index]

    reason_code = data.get('reason_code')
    if reason_code not in models.CHECKPOINT_FLAG_REASONS:
        return jsonify({'error': 'Bitte sag kurz, was mit der Frage nicht stimmt.'}), 400

    subtask_id = subtask['id']
    qidx = str(question_index)
    progress = _checkpoint_progress(subtask_id)

    if progress['solved'].get(qidx) or progress['gave_up'].get(qidx) or progress['flagged'].get(qidx):
        return jsonify({'error': 'Diese Frage ist schon abgeschlossen.'}), 400

    # "Die KI erkennt meine Antwort nicht an" is a claim about a verdict, so there
    # has to BE a verdict: at least one answer graded wrong on this question.
    # Ungated it would be the most attractive option on the list and the only one a
    # student could pick without ever typing anything.
    if reason_code == 'ki_bewertung' and progress['attempts'].get(qidx, 0) < 1:
        return jsonify({'error': ('Diesen Grund kannst du erst wählen, wenn du die Frage '
                                  'mindestens einmal beantwortet hast.')}), 400

    if models.get_open_student_flag(student_id, subtask_id, question_index):
        return jsonify({'error': 'Du hast diese Frage schon gemeldet.'}), 400

    progress['flagged'][qidx] = True
    _save_checkpoint_progress(subtask_id, progress)

    # The draft, if there is one. Serialized exactly like a graded answer so the
    # review UI and both exports read it the same way (see student_checkpoint_answer).
    draft = data.get('answer')
    draft_text = (json.dumps(draft, ensure_ascii=False)
                  if isinstance(draft, (list, dict)) else (draft or '').strip())
    if draft_text:
        models.create_checkpoint_answer(
            student_id, subtask_id, progress['session_uid'], question_index,
            attempt_no=progress['attempts'].get(qidx, 0) + 1, answer_text=draft_text,
            correct=None, feedback=None, grader='flagged',
            hints_used_before=progress['hints_used'].get(qidx, 0)
        )

    models.create_checkpoint_flag(
        subtask_id, question_index, source='student', student_id=student_id,
        session_uid=progress['session_uid'], reason_code=reason_code,
        reason_text=(data.get('reason_text') or '').strip()[:1000] or None,
        # The question as it read today: content gets edited, and without this a
        # report outlives the thing it describes.
        question_text_at_flag=question.get('text')
    )
    models.log_analytics_event(
        event_type='checkpoint_flag', user_id=student_id, user_type='student',
        metadata={'subtask_id': subtask_id, 'question_index': question_index,
                  'reason_code': reason_code}
    )
    return jsonify({'flagged': True, 'message': CHECKPOINT_FLAGGED_LOCK_MESSAGE})


def _consolidate_question_scores(scores):
    """The stored per-question breakdown -> the one session score, per
    chemie-data-contract.md 3a: min() across the questions that count.

    Same rule as _score_checkpoint_session, applied to the STORED breakdown rather
    than to a live sitting -- which is what the two after-the-fact paths need (a
    student redoing one question, a teacher setting one by hand). Kept in one place
    because the two used to spell it out separately and only ever agreed by luck.

    None = the question does not count (reported, or set to "zählt nicht"). The
    legacy 'vorher' key counts: on an attempt that predates per-question scores it
    stands for everything not broken out, and dropping it would let one hand-set 3
    lift a session above what it earned.

    Nothing left to take a min() over is 0, not None -- the Kern-Sperre reads a
    number and nothing else, so the floor has to be a number. A teacher voiding a
    whole session wants the session-level teacher_score override instead, which
    effective_checkpoint_score() lets win.
    """
    counted = [v for v in scores.values() if v is not None]
    return min(counted) if counted else 0


def _finish_checkpoint_retry(student_id, subtask_id, slug, progress, question_results):
    """End a redo of the questions whose report a teacher rejected.

    Rescores the EXISTING attempt instead of creating a second one: this is the
    same graded session, with the gaps filled in. So no new checkpoint_attempt, no
    re-ticking the Aufgabe, no second task_complete -- all of which already
    happened when the session was first finished.
    """
    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    if not attempt:
        # The attempt was reset while the redo was open. Nothing to rescore, and
        # writing a fresh one here would silently turn a redo into a full sitting.
        _clear_checkpoint_progress(subtask_id)
        return jsonify({'error': ('Dieser Checkpoint wurde neu geöffnet. Lade die Seite neu '
                                  'und bearbeite ihn von vorn.')}), 409

    if attempt.get('question_scores_json'):
        scores = json.loads(attempt['question_scores_json'])
    else:
        # An attempt from before per-question scores were stored. All that is known
        # about the other questions is the min() they produced, so keep it as a
        # floor -- the redo may lower the score, never invent a higher one.
        scores = {'vorher': attempt['score']}

    scores.update(zip(
        (str(r['index']) for r in question_results),
        _checkpoint_question_scores(question_results)
    ))
    score = _consolidate_question_scores(scores)

    models.update_checkpoint_attempt_scores(attempt['id'], scores, score)
    models.attach_checkpoint_session_to_attempt(progress['session_uid'], attempt['id'])
    models.mark_checkpoint_flags_retried(progress.get('retry_flag_ids') or [])
    models.log_analytics_event(
        event_type='checkpoint_flag_retry', user_id=student_id, user_type='student',
        metadata={'subtask_id': subtask_id, 'attempt_id': attempt['id'], 'score': score,
                  'questions': [r['index'] for r in question_results]}
    )
    _clear_checkpoint_progress(subtask_id)

    solved = sum(1 for r in question_results if r['solved'])
    total = len(question_results)
    return jsonify({
        'score': score,
        'score_reason': (f'{solved} von {total} nachgeholten Fragen gelöst. '
                         'Nachgeholte Fragen zählen höchstens '
                         f'{REJECTED_FLAG_RETRY_CAP} Punkte.'),
        'needs_review': False, 'flagged_count': 0, 'retry': True,
        'redirect_url': url_for('student_klasse', slug=slug)
    })


@app.route('/schueler/checkpoint/fertig', methods=['POST'])
@student_required
def student_checkpoint_finish():
    """AJAX: end the checkpoint session, score it, log to checkpoint_attempt,
    then advance progression exactly like a passed subtask quiz."""
    student_id = session['student_id']
    data = request.get_json() or {}
    slug = data.get('slug')
    task, subtask = _resolve_checkpoint_subtask(student_id, slug, data.get('subtask_id'))
    if not subtask:
        return jsonify({'error': 'Not found'}), 404

    subtask_id = subtask['id']
    questions = json.loads(subtask['quiz_json']).get('questions', [])
    progress = _checkpoint_progress(subtask_id)

    # The questions this session actually rendered, not the whole stored quiz --
    # see _handle_checkpoint_quiz. The fallback keeps a session that was already
    # running before `rendered` existed finishable.
    rendered = progress.get('rendered') or list(range(len(questions)))
    capped = (set(progress['retry_capped']) if 'retry_capped' in progress else None)

    question_results = []
    for i in rendered:
        qidx = str(i)
        solved = progress['solved'].get(qidx, False)
        gave_up = progress['gave_up'].get(qidx, False)
        # Third terminal state next to solved and gave_up: reported as broken. It
        # ends the question without ending it in a score -- see
        # _checkpoint_question_scores.
        flagged = progress['flagged'].get(qidx, False)
        if not solved and not gave_up and not flagged:
            return jsonify({'error': 'Checkpoint noch nicht abgeschlossen.'}), 400
        question_results.append({
            'index': i,
            'solved': solved,
            'gave_up': gave_up,
            'flagged': flagged,
            # Caps a redone question at REJECTED_FLAG_RETRY_CAP: the student had a
            # second look at it with the clock stopped, which is what a retry costs
            # anywhere else in this scoring rule. Only for a REJECTED report -- a
            # question the teacher sent back is our fault and costs the student
            # nothing. The fallback caps everything, which is what a session started
            # before retry_capped existed meant by retry=True.
            'retry_after_rejected_flag': (i in capped if capped is not None
                                          else bool(progress.get('retry'))),
            'attempts': progress['attempts'].get(qidx, 0),
            'hints_used': progress['hints_used'].get(qidx, 0),
            # True only if an /antwort call for this question got correct=None
            # (LLM grading unavailable) at least once -- see student_checkpoint_answer.
            'llm_error': progress.get('llm_errors', {}).get(qidx, 0) > 0,
        })

    if progress.get('retry'):
        return _finish_checkpoint_retry(student_id, subtask_id, slug, progress,
                                        question_results)

    score = _score_checkpoint_session(question_results)
    score_reason = _checkpoint_score_reason(question_results)
    # Keyed by the question's index in the STORED quiz, not by position in this
    # list: the session may have rendered a subset, and rescoring one question
    # after a rejected report has to find it again. A key that is present with a
    # null value = reported, no score yet; a missing key = not part of this session.
    question_scores = json.dumps(dict(zip(
        (str(r['index']) for r in question_results),
        _checkpoint_question_scores(question_results)
    )))
    flagged_count = sum(1 for r in question_results if r['flagged'])
    total_attempts = sum(r['attempts'] for r in question_results) or 1
    total_hints = sum(r['hints_used'] for r in question_results)

    # A give-up only needs manual review if it was forced by an LLM failure, not
    # a genuine "student didn't know it" -- otherwise the 0 stands as-is.
    review_questions = [r['index'] for r in question_results if r['gave_up'] and r['llm_error']]
    needs_review = bool(review_questions)
    review_notes = json.dumps({'questions': review_questions}) if needs_review else None

    student_task_id = task['id']
    models.create_checkpoint_attempt(
        student_id, checkpoint_id=subtask_id, module_id=task['task_id'],
        checkpoint_type='quiz', kern_standard_tag=subtask['kern_standard_tag'],
        score=score, attempt_count=total_attempts, hint_count=total_hints,
        needs_review=needs_review, review_notes=review_notes,
        quiz_snapshot_json=subtask['quiz_json'], session_uid=progress['session_uid'],
        question_scores_json=question_scores
    )
    models.log_analytics_event(
        event_type='checkpoint_attempt', user_id=student_id, user_type='student',
        metadata={'student_task_id': student_task_id, 'subtask_id': subtask_id, 'score': score,
                  'needs_review': needs_review, 'flagged_count': flagged_count}
    )

    toggle_result = models.toggle_student_subtask(student_task_id, subtask_id, True)
    if not toggle_result.get('quiz_pending') and models.check_task_completion(student_task_id):
        models.mark_task_complete(student_task_id)
        models.log_analytics_event(
            event_type='task_complete', user_id=student_id, user_type='student',
            metadata={'student_task_id': student_task_id}
        )

    all_progress = session.get('checkpoint_progress', {})
    all_progress.pop(str(subtask_id), None)
    session['checkpoint_progress'] = all_progress

    return jsonify({
        'score': score, 'score_reason': score_reason, 'needs_review': needs_review,
        'flagged_count': flagged_count,
        'redirect_url': url_for('student_klasse', slug=slug)
    })


@app.route('/schueler/thema/<slug>/quiz-ergebnis')
@student_required
def student_quiz_result(slug):
    """View most recent topic quiz result."""
    student_id = session['student_id']
    student = models.get_student(student_id)

    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    attempts = models.get_quiz_attempts(task['id'])
    if not attempts:
        flash('Du hast dieses Quiz noch nicht gemacht.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    latest = attempts[0]
    ever_passed = any(a['bestanden'] for a in attempts)
    quiz = _filter_quiz_for_path(json.loads(task['quiz_json']), student)
    antworten = json.loads(latest['antworten_json']) if latest['antworten_json'] else {}

    next_topic = None
    if ever_passed and klasse:
        next_topic = models.get_next_queued_topic(klasse['id'], task['task_id'])

    display_quiz, antworten = _apply_question_order(_build_display_quiz(quiz), antworten)
    transparency_mode = models.get_effective_transparency_mode(student_id, klasse['id'] if klasse else None)
    return render_template('student/quiz_result.html',
                           student=student, task=task,
                           quiz=display_quiz,
                           punkte=latest['punkte'], max_punkte=latest['max_punkte'],
                           bestanden=latest['bestanden'], antworten=antworten,
                           ever_passed=ever_passed,
                           previous_attempt=attempts[1] if len(attempts) > 1 else None,
                           slug=slug, position=None,
                           quiz_bestanden=ever_passed,
                           next_topic=next_topic, klasse=klasse,
                           transparency_mode=transparency_mode)


@app.route('/schueler/thema/<slug>/aufgabe-<int:position>/quiz-ergebnis')
@student_required
def student_quiz_result_subtask(slug, position):
    """View most recent subtask quiz result."""
    student_id = session['student_id']
    student = models.get_student(student_id)

    task, klasse = _resolve_student_topic(student_id, slug)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Resolve subtask by position
    all_subtasks = models.get_student_subtask_progress(task['id'])
    visible_subtask_ids = [s['id'] for s in models.get_visible_subtasks_for_student(
        student_id, klasse['id'], task['task_id']
    )]
    subtasks = [st for st in all_subtasks if st['id'] in visible_subtask_ids]
    subtask = _resolve_subtask_by_position(subtasks, position)

    if not subtask:
        flash('Aufgabe nicht gefunden.', 'danger')
        return redirect(url_for('student_klasse', slug=slug))

    attempts = models.get_quiz_attempts(task['id'], subtask_id=subtask['id'])
    if not attempts:
        flash('Du hast dieses Quiz noch nicht gemacht.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    latest = attempts[0]
    ever_passed = models.has_passed_subtask_quiz(task['id'], subtask['id'])
    with models.db_session() as conn:
        subtask_row = conn.execute("SELECT quiz_json FROM subtask WHERE id = ?", (subtask['id'],)).fetchone()

    quiz = _filter_quiz_for_path(json.loads(subtask_row['quiz_json']), student)
    antworten = json.loads(latest['antworten_json']) if latest['antworten_json'] else {}

    next_position = position + 1 if position < len(subtasks) else None
    topic_quiz_attempts = models.get_quiz_attempts(task['id'])
    quiz_bestanden = any(a['bestanden'] for a in topic_quiz_attempts)

    display_quiz, antworten = _apply_question_order(_build_display_quiz(quiz), antworten)
    transparency_mode = models.get_effective_transparency_mode(student_id, klasse['id'] if klasse else None)
    return render_template('student/quiz_result.html',
                           student=student, task=task,
                           quiz=display_quiz,
                           punkte=latest['punkte'], max_punkte=latest['max_punkte'],
                           bestanden=latest['bestanden'], antworten=antworten,
                           ever_passed=ever_passed,
                           previous_attempt=attempts[1] if len(attempts) > 1 else None,
                           slug=slug, position=position,
                           next_position=next_position,
                           quiz_bestanden=quiz_bestanden,
                           transparency_mode=transparency_mode)


@app.route('/schueler/thema/<slug>/drucken')
@student_required
def student_print_topic(slug):
    student_id = session['student_id']
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task or not klasse:
        return redirect(url_for('student_dashboard'))
    subtasks = models.get_visible_subtasks_for_student(student_id, klasse['id'], task['task_id'])
    for sub in subtasks:
        sub['materials'] = models.get_materials_for_subtask(task['task_id'], sub['id'])
    return render_template('student/print_tasks.html', task=task, subtasks=subtasks, single=False)


@app.route('/schueler/thema/<slug>/aufgabe-<int:position>/drucken')
@student_required
def student_print_subtask(slug, position):
    student_id = session['student_id']
    task, klasse = _resolve_student_topic(student_id, slug)
    if not task or not klasse:
        return redirect(url_for('student_dashboard'))
    subtasks = models.get_visible_subtasks_for_student(student_id, klasse['id'], task['task_id'])
    subtask = _resolve_subtask_by_position(subtasks, position)
    if not subtask:
        return redirect(url_for('student_klasse', slug=slug))
    subtask['materials'] = models.get_materials_for_subtask(task['task_id'], subtask['id'])
    return render_template('student/print_tasks.html', task=task, subtasks=[subtask], single=True)


@app.route('/schueler/unterricht/<int:unterricht_id>/selbstbewertung', methods=['POST'])
@student_required
def student_selbstbewertung(unterricht_id):
    student_id = session['student_id']
    selbst_selbst = int(request.form.get('selbst_selbststaendigkeit', 2))
    selbst_respekt = int(request.form.get('selbst_respekt', 2))

    models.update_student_self_eval(unterricht_id, student_id, selbst_selbst, selbst_respekt)
    flash('Selbstbewertung gespeichert. ✅', 'success')
    return redirect(request.referrer or url_for('student_dashboard'))


@app.route('/schueler/naechstes-thema', methods=['POST'])
@student_required
def student_start_next_topic():
    """Start the next topic from the class queue."""
    student_id = session['student_id']
    task_id = request.form.get('task_id', type=int)
    klasse_id = request.form.get('klasse_id', type=int)

    if not task_id or not klasse_id:
        flash('Da ist etwas schiefgelaufen. Bitte die Seite neu laden.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Validate: student is in this class
    klassen = models.get_student_klassen(student_id)
    if not any(k['id'] == klasse_id for k in klassen):
        flash('Da ist etwas schiefgelaufen. Bitte die Seite neu laden.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Validate: task_id is in the class queue
    queue = models.get_topic_queue(klasse_id)
    if not any(q['task_id'] == task_id for q in queue):
        flash('Dieses Thema ist noch nicht dran.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Get task name for flash message and redirect
    task = models.get_task(task_id)
    if not task:
        flash('Da ist etwas schiefgelaufen. Bitte die Seite neu laden.', 'danger')
        return redirect(url_for('student_dashboard'))

    models.assign_task_to_student(student_id, klasse_id, task_id)

    models.log_analytics_event(
        event_type='topic_progression',
        user_id=student_id,
        user_type='student',
        metadata={'task_id': task_id, 'klasse_id': klasse_id}
    )

    flash(f'Neues Thema gestartet: {task["name"]} 🎉', 'success')
    return redirect(url_for('student_klasse', slug=slugify(task['name'])))


@app.route('/schueler/einstellungen', methods=['GET', 'POST'])
@student_required
def student_settings():
    """Student settings page (Easy Reading Mode)."""
    student_id = session['student_id']

    if request.method == 'POST':
        easy_reading_mode = 1 if request.form.get('easy_reading_mode') == 'on' else 0
        models.update_student_setting(student_id, 'easy_reading_mode', easy_reading_mode)
        transparency_mode = 1 if request.form.get('llm_transparency_mode') == 'on' else 0
        models.update_student_setting(student_id, 'llm_transparency_mode', transparency_mode)
        step_checkboxes = 1 if request.form.get('step_checkboxes') == 'on' else 0
        models.update_student_setting(student_id, 'step_checkboxes', step_checkboxes)

        flash('Einstellungen gespeichert! ✅', 'success')
        return redirect(url_for('student_settings'))

    student = models.get_student(student_id)
    return render_template('student/settings.html', student=student)


# ============ Warmup / Spaced Repetition ============

def _grade_warmup_answer(question, answer, usage_tag='llm_grading', strict=False):
    """Grade a single warmup answer.

    Returns (correct: bool|None, feedback: str, source: str, prompt_version: str|None,
    confidence: float|None).

    MC: compare selected indices to correct set.
    fill_blank: case-insensitive exact match, then LLM fallback.
    short_answer: rubric-graded via LLM (no exact match, free text).
    ordering/matching: deterministic, via quiz_grading (never an LLM call).
    source: 'match' | 'llm' | 'fallback' | 'empty' | 'mc' | 'interactive' | 'error'

    prompt_version identifies which system prompt graded the answer
    (llm_grading.prompt_version_for) and is None whenever no LLM was involved --
    an exact match, an MC comparison or an empty submit must not be stamped with a
    prompt that never saw them (migrate_048). It is threaded through here rather
    than re-derived by the caller because only grade_answer knows which prompt its
    usage_tag actually selected. confidence follows the same rule for the same reason
    (migrate_052): None for every path no LLM graded, and only ever populated for
    checkpoints, which are the only calls that ask for logprobs.

    usage_tag/strict: passed through to llm_grading.grade_answer (see there). When
    strict=True and grading could not happen at all, correct is None, not False --
    callers must not treat that as a wrong answer (see student_checkpoint_answer).
    """
    qtype = question.get('type', 'multiple_choice')

    if quiz_grading.is_interactive(qtype):
        # Deterministic: no LLM call, so strict= and usage_tag= have nothing to
        # act on and this can never return None. `correct` stays all-or-nothing --
        # a partly right answer must not clear a checkpoint gate or a warm-up
        # streak; the fraction lives in the feedback line instead.
        result = quiz_grading.grade(question, answer)
        return result['correct'], result['feedback'], 'interactive', None, None

    if qtype == 'fill_blank':
        student_text = (answer or '').strip()
        if not student_text:
            return False, 'Keine Antwort.', 'empty', None, None
        # Exact match (case-insensitive)
        if student_text.lower() in [a.lower() for a in question['answers']]:
            return True, 'Richtig!', 'match', None, None
        # LLM fallback
        result = llm_grading.grade_answer(
            question['text'], ', '.join(question['answers']),
            student_text, session.get('student_id'), usage_tag=usage_tag, strict=strict
        )
        if result is None:
            return None, '', 'error', None, None
        return (result['correct'], result.get('feedback', ''), result.get('source', 'llm'),
                result.get('prompt_version'), result.get('confidence'))
    elif qtype == 'short_answer':
        student_text = (answer or '').strip()
        if not student_text:
            return False, 'Keine Antwort.', 'empty', None, None
        result = llm_grading.grade_answer(
            question['text'], question['rubric'],
            student_text, session.get('student_id'), usage_tag=usage_tag, strict=strict
        )
        if result is None:
            return None, '', 'error', None, None
        return (result['correct'], result.get('feedback', ''), result.get('source', 'llm'),
                result.get('prompt_version'), result.get('confidence'))
    else:
        # Multiple choice
        try:
            submitted = set(int(x) for x in answer) if answer else set()
        except (ValueError, TypeError):
            submitted = set()
        correct_set = set(question.get('correct', []))
        if submitted == correct_set:
            return True, 'Richtig!', 'mc', None, None
        # Build feedback showing correct answer(s)
        options = question.get('options', [])
        correct_texts = []
        for idx in correct_set:
            if idx < len(options):
                opt = options[idx]
                correct_texts.append(opt['text'] if isinstance(opt, dict) else str(opt))
        return False, f'Richtige Antwort: {", ".join(correct_texts)}', 'mc', None, None


def _serialize_question_for_js(item):
    """Convert a pool item to a JSON-safe dict for the frontend."""
    q = item['question']
    result = {
        'task_id': item['task_id'],
        'subtask_id': item['subtask_id'],
        'question_index': item['question_index'],
        'topic_name': item['topic_name'],
        'fach': item.get('fach'),
        'type': q.get('type', 'multiple_choice'),
        'text': q['text'],
    }
    if result['type'] == 'fill_blank':
        # Don't send answers to client
        pass
    elif quiz_grading.is_interactive(result['type']):
        # Shuffled pieces only. For ordering the authored order *is* the answer,
        # so sending `items` unshuffled would hand it over outright.
        result.update(quiz_grading.presentation(q))
    else:
        # MC: send options + correct_count (single- vs multi-select rendering)
        # only -- never the correct indices themselves before grading. Grading
        # happens server-side in student_warmup_answer, which rebuilds the
        # question from the pool; the /antwort response carries correct_answer
        # for post-answer highlighting.
        options = q.get('options', [])
        result['options'] = options
        result['correct_count'] = len(q.get('correct', []))
    if q.get('image'):
        result['image'] = q['image']
    return result


@app.route('/schueler/aufwaermen')
@student_required
def student_warmup():
    """Warmup page — 3 mixed questions."""
    student_id = session['student_id']
    student = models.get_student(student_id)

    # Already done today? → dashboard
    if models.has_done_warmup_today(student_id):
        return redirect(url_for('student_dashboard'))

    pool = models.get_warmup_question_pool(student_id)
    if not pool:
        return redirect(url_for('student_dashboard'))

    questions = models.select_warmup_questions(student_id, pool, difficulty='mixed', count=3)
    if not questions:
        return redirect(url_for('student_dashboard'))

    questions_json = json.dumps([_serialize_question_for_js(q) for q in questions])
    return render_template('student/warmup.html', student=student,
                           questions_json=questions_json,
                           llm_enabled=config.LLM_ENABLED)


@app.route('/schueler/aufwaermen/antwort', methods=['POST'])
@student_required
def student_warmup_answer():
    """AJAX: grade a single warmup answer."""
    student_id = session['student_id']
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400

    task_id = data.get('task_id')
    subtask_id = data.get('subtask_id')
    question_index = data.get('question_index')
    answer = data.get('answer')

    # Rebuild the question from source to prevent client-side tampering
    pool = models.get_warmup_question_pool(student_id)
    matched = None
    for item in pool:
        if (item['task_id'] == task_id and
                item['subtask_id'] == subtask_id and
                item['question_index'] == question_index):
            matched = item
            break

    if matched is None:
        return jsonify({'error': 'Question not found'}), 404
    question = matched['question']

    correct, feedback, source, _prompt_version, _confidence = _grade_warmup_answer(question, answer)
    models.record_warmup_answer(student_id, task_id, subtask_id, matched['question_hash'], correct)

    # Build correct_answer for feedback display
    # MC: always send correct indices (needed for ✅/❌ highlighting on all options)
    # fill_blank: only send on wrong answer (shows expected answer)
    qtype = question.get('type', 'multiple_choice')
    correct_answer = None
    if qtype == 'fill_blank':
        if not correct:
            correct_answer = question['answers'][0] if question.get('answers') else None
    elif quiz_grading.is_interactive(qtype):
        if not correct:
            correct_answer = quiz_grading.correct_answer_text(question)
    else:
        correct_answer = question.get('correct', [])

    response = {'correct': correct, 'feedback': feedback, 'source': source, 'correct_answer': correct_answer}

    # Transparency mode: include prompt data when LLM was used
    if source == 'llm' and models.get_effective_transparency_mode(student_id):
        response['prompt_data'] = {
            'question': question['text'],
            'expected': ', '.join(question.get('answers', [])),
            'student_answer': (answer or '').strip(),
        }

    return jsonify(response)



@app.route('/schueler/aufwaermen/fertig', methods=['POST'])
@student_required
def student_warmup_finish():
    """AJAX: save warmup session stats."""
    student_id = session['student_id']
    data = request.get_json() or {}
    models.save_warmup_session(
        student_id,
        questions_shown=data.get('questions_shown', 0),
        questions_correct=data.get('questions_correct', 0),
        skipped=data.get('skipped', False),
        session_type=data.get('session_type', 'warmup')
    )
    return jsonify({'ok': True})


@app.route('/schueler/ueben')
@student_required
def student_practice():
    """Practice mode — student-initiated review session."""
    student_id = session['student_id']
    student = models.get_student(student_id)
    mode = request.args.get('mode', 'random')
    topic_slug = request.args.get('thema')

    pool = models.get_warmup_question_pool(student_id)
    if not pool:
        flash('Noch keine Fragen zum Üben verfügbar.', 'info')
        return redirect(url_for('student_dashboard'))

    # Collect unique topic names for the topic selector
    topic_names = sorted(set(q['topic_name'] for q in pool))

    # Filter by topic if requested
    if mode == 'thema' and topic_slug:
        pool = [q for q in pool if slugify(q['topic_name']) == topic_slug]

    # Select questions based on mode. Thema mode is deliberate focused review,
    # so it gets longer sessions than the quick-dip random/schwaechen modes.
    if mode == 'schwaechen':
        questions = models.select_warmup_questions(student_id, pool, difficulty='hard', count=5, respect_intervals=False)
    else:
        count = 10 if mode == 'thema' and topic_slug else 5
        questions = models.select_warmup_questions(student_id, pool, difficulty='mixed', count=count, respect_intervals=False)

    if not questions:
        flash('Keine passenden Fragen gefunden.', 'info')
        return redirect(url_for('student_practice', mode='random'))

    practice_sessions_today = models.count_practice_sessions_today(student_id)
    questions_json = json.dumps([_serialize_question_for_js(q) for q in questions])
    return render_template('student/practice.html', student=student,
                           questions_json=questions_json, mode=mode,
                           topic_names=topic_names, selected_topic=topic_slug,
                           pool_size=len(pool), shown_count=len(questions),
                           practice_sessions_today=practice_sessions_today,
                           llm_enabled=config.LLM_ENABLED)


# ============ Error Handlers ============

def get_current_user_info():
    """Extract current user info from session for error logging."""
    user_id = None
    user_type = None

    if 'admin_id' in session:
        user_id = session['admin_id']
        user_type = 'admin'
    elif 'student_id' in session:
        user_id = session['student_id']
        user_type = 'student'

    return user_id, user_type


# Routes the browser calls with fetch() and reads as JSON. An error on one of
# these used to fall through to the handlers below, which flash + redirect: the
# student's upload came back as a 302 to the dashboard with an HTML body, so the
# JS saw no error message at all and the page just went quiet. A 65 MB
# photo-heavy .pptx did exactly this.
_JSON_UPLOAD_ENDPOINTS = frozenset({
    'student_artifact_preview',
    'student_artifact_feedback',
    'student_artifact_gate_check',
})


def _wants_json_error():
    return request.endpoint in _JSON_UPLOAD_ENDPOINTS


@app.errorhandler(413)
def handle_too_large(error):
    """Upload above MAX_CONTENT_LENGTH -- say so, in the shape the caller reads."""
    limit_mb = config.MAX_CONTENT_LENGTH // (1024 * 1024)
    message = (f'Die Datei ist zu groß (Maximum: {limit_mb} MB). '
               f'Bitte verkleinere sie und versuche es noch einmal.')
    if _wants_json_error():
        return jsonify({'error': message}), 413
    flash(message, 'danger')
    return redirect(request.referrer or url_for('index'))


@app.errorhandler(400)
def handle_bad_request(error):
    """Handle 400 Bad Request errors."""
    user_id, user_type = get_current_user_info()
    models.log_error(
        level='WARNING',
        message=f'Bad Request: {str(error)}',
        traceback=traceback.format_exc(),
        user_id=user_id,
        user_type=user_type,
        route=request.endpoint,
        method=request.method,
        url=request.url
    )
    flash('Da ist etwas schiefgelaufen. Bitte die Seite neu laden.', 'warning')
    return redirect(request.referrer or url_for('index'))


@app.errorhandler(403)
def handle_forbidden(error):
    """Handle 403 Forbidden errors."""
    user_id, user_type = get_current_user_info()
    models.log_error(
        level='WARNING',
        message=f'Forbidden: {str(error)}',
        traceback=None,
        user_id=user_id,
        user_type=user_type,
        route=request.endpoint,
        method=request.method,
        url=request.url
    )
    flash('Zugriff verweigert.', 'danger')
    return redirect(url_for('index'))


@app.errorhandler(404)
def handle_not_found(error):
    """Handle 404 Not Found errors."""
    # Don't log 404s to database (too noisy), just show error page
    return render_template('error.html',
                         error_code=404,
                         error_message='Seite nicht gefunden'), 404


@app.errorhandler(405)
def handle_method_not_allowed(error):
    """Handle 405 Method Not Allowed errors (usually bots probing the server)."""
    # Don't log 405s to database (too noisy from bots), just show error page
    return render_template('error.html',
                         error_code=405,
                         error_message='Methode nicht erlaubt'), 405


@app.errorhandler(500)
def handle_internal_error(error):
    """Handle 500 Internal Server errors."""
    user_id, user_type = get_current_user_info()
    models.log_error(
        level='ERROR',
        message=f'Internal Server Error: {str(error)}',
        traceback=traceback.format_exc(),
        user_id=user_id,
        user_type=user_type,
        route=request.endpoint,
        method=request.method,
        url=request.url
    )
    flash('Ein interner Fehler ist aufgetreten. Der Fehler wurde protokolliert.', 'danger')
    return redirect(url_for('index'))


@app.errorhandler(Exception)
def handle_exception(error):
    """Handle all unhandled exceptions."""
    # Skip errors handled by dedicated handlers
    if isinstance(error, Exception) and error.__class__.__name__ == 'NotFound':
        return handle_not_found(error)
    if isinstance(error, Exception) and error.__class__.__name__ == 'MethodNotAllowed':
        return handle_method_not_allowed(error)

    user_id, user_type = get_current_user_info()
    models.log_error(
        level='CRITICAL',
        message=f'Unhandled Exception: {error.__class__.__name__}: {str(error)}',
        traceback=traceback.format_exc(),
        user_id=user_id,
        user_type=user_type,
        route=request.endpoint,
        method=request.method,
        url=request.url
    )
    if _wants_json_error():
        return jsonify({'error': 'Beim Verarbeiten der Datei ist etwas schiefgelaufen. '
                                 'Bitte versuche es noch einmal.'}), 500
    flash('Ein unerwarteter Fehler ist aufgetreten. Der Fehler wurde protokolliert.', 'danger')
    return redirect(url_for('index'))


# ============ Analytics Middleware ============

@app.after_request
def set_security_headers(response):
    """Stop the browser second-guessing the Content-Type we declared.

    Without it a browser may inspect the bytes and decide an upload we serve as
    image/jpeg is really a page, which turns a renamed file into a script on our
    own origin. It is insurance, not the control: a file we *declare* as
    text/html still renders, which is why download_material only serves
    config.INLINE_EXTENSIONS inline in the first place.

    In app rather than nginx so it holds in development too, and so it cannot be
    lost the next time certbot rewrites the server block.
    """
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    return response


@app.before_request
def log_analytics():
    """Automatically log page views and activity."""
    # Skip static files
    if request.path.startswith('/static/'):
        return

    # Skip favicon
    if request.path == '/favicon.ico':
        return

    # Skip analytics pages (avoid logging while viewing analytics)
    if request.path.startswith('/admin/analytics'):
        return

    # Skip error logs page
    if request.path.startswith('/admin/errors'):
        return

    # Skip file downloads (logged manually)
    if '/download' in request.path:
        return

    # Only log authenticated requests
    user_id = None
    user_type = None
    if 'admin_id' in session:
        user_id = session['admin_id']
        user_type = 'admin'
    elif 'student_id' in session:
        user_id = session['student_id']
        user_type = 'student'
    else:
        return  # Don't log unauthenticated requests

    # Log page view (if enabled)
    if app.config.get('LOG_PAGE_VIEWS', True):
        models.log_analytics_event(
            event_type='page_view',
            user_id=user_id,
            user_type=user_type,
            metadata={
                'route': request.endpoint,
                'method': request.method,
                'path': request.path
            }
        )


# ============ Initialize ============

@app.cli.command('auto-attendance')
def cli_auto_attendance():
    """Auto-fill attendance for all classes scheduled today."""
    init_app()
    results = models.auto_fill_all_scheduled_today()
    if not results:
        print("No classes scheduled today.")
        return
    for r in results:
        print(f"{r['klasse_name']}: {r['present']} present, {r['absent']} absent, {r['skipped']} skipped")


def init_app():
    """Initialize the application."""
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)  # instance/uploads
    os.makedirs(os.path.join(os.path.dirname(config.UPLOAD_FOLDER), 'tmp'), exist_ok=True)  # instance/tmp
    os.makedirs(os.path.dirname(config.DATABASE), exist_ok=True)  # data/
    models.init_db()

    # Start async analytics worker thread
    from analytics_queue import start_worker
    start_worker()
    print("Analytics worker thread started")

    # Load app settings into config (cached for performance)
    app.config['LOG_PAGE_VIEWS'] = models.get_bool_setting('log_page_views', default=True)
    app.config['STUDENT_CLEAR_NAMES'] = models.get_bool_setting('student_clear_names', default=True)
    print(f"Page view logging: {'enabled' if app.config['LOG_PAGE_VIEWS'] else 'disabled'}")

    # Create default admin if not exists
    if models.create_admin('admin', 'admin'):
        print("Default admin created: admin/admin")


if __name__ == '__main__':
    init_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
