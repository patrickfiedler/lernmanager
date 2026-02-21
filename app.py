import os
import json
import traceback
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
from utils import generate_username, generate_password, allowed_file, generate_credentials_pdf, generate_student_self_report_pdf, slugify
from import_task import validate_task_structure, check_duplicate, import_task as do_import_task, ValidationError

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
    html = md.markdown(text, extensions=['nl2br', 'fenced_code', 'tables', 'sane_lists'], tab_length=3)
    return Markup(html)


@app.template_filter('slugify')
def slugify_filter(text):
    """Convert text to URL-friendly slug."""
    return slugify(text)


# ============ Helpers ============

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


def _resolve_student_topic(student_id, slug):
    """Find student_task matching topic slug. Returns (task, klasse) or (None, None).

    Searches all student_task rows (active + completed, all roles) so students
    can still view completed topics' quiz results and history.
    """
    klassen = models.get_student_klassen(student_id)
    for klasse in klassen:
        tasks = models.get_all_student_tasks(student_id, klasse['id'])
        for task in tasks:
            if slugify(task['name']) == slug:
                return task, klasse
    return None, None


def _resolve_subtask_by_position(subtasks, position):
    """Find subtask at 1-based position in ordered list. Returns subtask or None."""
    if 1 <= position <= len(subtasks):
        return subtasks[position - 1]
    return None


def _build_display_quiz(quiz):
    """Transform quiz JSON (text/options) to template format (question/answers)."""
    return {
        'questions': [
            {
                'question': q['text'],
                'answers': q.get('options', []),
                'correct': q.get('correct', []),
                'image': q.get('image'),
                'type': q.get('type', 'multiple_choice')
            }
            for q in quiz['questions']
        ]
    }


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
            session['student_name'] = f"{student['vorname']} {student['nachname']}"
            # Log login event
            models.log_analytics_event(
                event_type='login',
                user_id=student['id'],
                user_type='student',
                metadata={'username': student['username']}
            )
            flash(f'Willkommen, {student["vorname"]}! 👋', 'success')
            return redirect(url_for('student_warmup'))

        flash('Ungültiger Benutzername oder Passwort.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Auf Wiedersehen! 👋', 'info')
    return redirect(url_for('login'))


# ============ Admin Dashboard ============

@app.route('/admin')
@admin_required
def admin_dashboard():
    klassen = models.get_all_klassen()
    tasks = models.get_all_tasks()

    # Filter classes for "Unterricht heute" based on schedule
    today_weekday = datetime.today().weekday()  # 0=Monday, 6=Sunday
    klassen_heute = []
    for klasse in klassen:
        schedule = models.get_class_schedule(klasse['id'])
        if schedule and schedule['weekday'] == today_weekday:
            klassen_heute.append(klasse)

    # Get page view logging setting
    log_page_views = models.get_bool_setting('log_page_views', default=True)

    return render_template('admin/dashboard.html', klassen=klassen, tasks=tasks,
                          klassen_heute=klassen_heute, log_page_views=log_page_views)


@app.route('/admin/settings', methods=['POST'])
@admin_required
def admin_update_settings():
    """Update application settings."""
    log_page_views = 'log_page_views' in request.form
    models.set_bool_setting('log_page_views', log_page_views)

    # Update cached value
    app.config['LOG_PAGE_VIEWS'] = log_page_views

    flash(f"Einstellung gespeichert: Seitenaufrufe protokollieren {'aktiviert' if log_page_views else 'deaktiviert'}",
          'success')
    return redirect(url_for('admin_dashboard'))


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

    return render_template('admin/klasse_detail.html', klasse=klasse, students=students,
                           tasks=tasks, unterricht=unterricht, schedule=schedule,
                           has_queue=bool(queue))


@app.route('/admin/klasse/<int:klasse_id>/loeschen', methods=['POST'])
@admin_required
def admin_klasse_loeschen(klasse_id):
    klasse = models.get_klasse(klasse_id)
    if klasse:
        models.delete_klasse(klasse_id)
        flash(f'Klasse "{klasse["name"]}" gelöscht.', 'success')
    return redirect(url_for('admin_klassen'))


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
    pdf_buffer = utils.generate_class_report_pdf(report_data, date_from=date_from, date_to=date_to)

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

            student_id = models.create_student(nachname, vorname, username, password)
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

    return render_template('admin/topic_queue.html',
                           klasse=klasse, queue=queue,
                           available_tasks=available_tasks)


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

    return render_template('admin/schueler_detail.html',
                           student=student,
                           klassen=klassen,
                           all_klassen=all_klassen,
                           tasks=tasks,
                           student_tasks=student_tasks)


@app.route('/admin/schueler/<int:student_id>/loeschen', methods=['POST'])
@admin_required
def admin_schueler_loeschen(student_id):
    models.delete_student(student_id)
    flash('Schüler gelöscht.', 'success')
    return redirect(request.referrer or url_for('admin_klassen'))


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
    pdf_buffer = utils.generate_student_report_pdf(report_data, report_type=report_type)

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
    return render_template('admin/aufgaben.html', tasks=tasks, subjects=config.SUBJECTS, levels=config.LEVELS)


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


def _build_topic_preview(task_data):
    """Build a preview dict for one topic from import JSON."""
    task = task_data['task']
    subtasks = task.get('subtasks', [])
    path_counts = {'wanderweg': 0, 'bergweg': 0, 'gipfeltour': 0}
    for s in subtasks:
        p = s.get('path', 'bergweg')
        if p in path_counts:
            path_counts[p] += 1
    return {
        'name': task['name'],
        'fach': task['fach'],
        'stufe': task['stufe'],
        'kategorie': task.get('kategorie', 'pflicht'),
        'number': task.get('number'),
        'subtask_count': len(subtasks),
        'path_counts': path_counts,
        'material_count': len(task.get('materials', [])),
        'topic_quiz_count': len(task['quiz']['questions']) if task.get('quiz') else 0,
        'subtask_quiz_count': sum(1 for s in subtasks if s.get('quiz')),
        'is_duplicate': check_duplicate(task_data) is not None,
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
        if not file or not file.filename.endswith('.json'):
            flash('Bitte eine JSON-Datei auswählen.', 'danger')
            return render_template('admin/themen_import.html', preview=False)

        try:
            raw = file.read().decode('utf-8')
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return render_template('admin/themen_import.html', preview=True,
                                   errors=[f'Ungültiges JSON: {e}'])

        # Normalize to list of {"task": {...}} dicts
        task_list = []
        errors = []
        if 'tasks' in data and isinstance(data['tasks'], list):
            for t in data['tasks']:
                wrapped = {'task': t}
                try:
                    validate_task_structure(wrapped)
                    task_list.append(wrapped)
                except ValidationError as e:
                    errors.append(f"{t.get('name', '?')}: {e}")
        elif 'task' in data:
            try:
                validate_task_structure(data)
                task_list.append(data)
            except ValidationError as e:
                errors.append(str(e))
        else:
            errors.append("JSON muss 'task' oder 'tasks' als Wurzelelement enthalten.")

        if errors:
            return render_template('admin/themen_import.html', preview=True, errors=errors)

        # Build preview for each topic
        topics_preview = [_build_topic_preview(td) for td in task_list]
        warnings = []
        for tp in topics_preview:
            if tp['is_duplicate']:
                warnings.append(f"'{tp['name']}' ({tp['fach']} {tp['stufe']}) existiert bereits — wird übersprungen.")

        # Re-serialize the validated data for the hidden form field
        export_data = {'tasks': [td['task'] for td in task_list]}
        json_data = json.dumps(export_data, ensure_ascii=False)

        return render_template('admin/themen_import.html', preview=True,
                               topics_preview=topics_preview, warnings=warnings,
                               json_data=json_data)

    # --- Confirm phase: actually import ---
    if action == 'confirm':
        raw = request.form.get('json_data', '')
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            flash('Ungültige Daten. Bitte erneut hochladen.', 'danger')
            return redirect(url_for('admin_themen_import'))

        imported = []
        skipped = []
        warnings = []
        for task_entry in data.get('tasks', []):
            wrapped = {'task': task_entry}
            w = []
            task_id = do_import_task(wrapped, warnings=w)
            warnings.extend(w)
            if task_id:
                imported.append(task_entry['name'])
            else:
                skipped.append(task_entry['name'])

        if imported:
            flash(f"{len(imported)} Thema{'en' if len(imported) > 1 else ''} importiert: {', '.join(imported)}", 'success')
        if skipped:
            flash(f"{len(skipped)} übersprungen (Duplikate): {', '.join(skipped)}", 'warning')
        for w in warnings:
            flash(w, 'warning')

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
            lernziel_schueler=request.form.get('lernziel_schueler') or None
        )
        flash('Thema erstellt. ✅', 'success')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    return render_template('admin/aufgabe_form.html', task=None, subjects=config.SUBJECTS, levels=config.LEVELS)


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
    return render_template('admin/aufgabe_detail.html', task=task, subtasks=subtasks, materials=materials, subjects=config.SUBJECTS, levels=config.LEVELS, material_assignments=material_assignments)


@app.route('/admin/thema/<int:task_id>/bearbeiten', methods=['POST'])
@admin_required
def admin_thema_bearbeiten(task_id):
    try:
        quiz_json = validate_quiz_json(request.form.get('quiz_json'))
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

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
        lernziel_schueler=request.form.get('lernziel_schueler') or None
    )
    flash('Thema aktualisiert. ✅', 'success')
    return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/admin/thema/<int:task_id>/loeschen', methods=['POST'])
@admin_required
def admin_thema_loeschen(task_id):
    models.delete_task(task_id)
    flash('Thema gelöscht.', 'success')
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

        # Validate all subtask quiz JSONs before saving
        for i, qj in enumerate(quiz_json_list):
            try:
                validate_quiz_json(qj)
            except ValueError as e:
                flash(f'Aufgabe {i+1} Quiz-JSON: {e}', 'danger')
                return redirect(url_for('admin_thema_detail', task_id=task_id))

        models.update_subtasks(task_id, subtasks_list, estimated_minutes_list, quiz_json_list,
                               path_list=path_list, path_model_list=path_model_list)
        flash('Aufgaben aktualisiert.', 'success')
        return redirect(url_for('admin_thema_detail', task_id=task_id))


@app.route('/admin/thema/<int:task_id>/material-link', methods=['POST'])
@admin_required
def admin_thema_material_link(task_id):
    url = request.form['url'].strip()
    beschreibung = request.form.get('beschreibung', '').strip()
    if url:
        models.create_material(task_id, 'link', url, beschreibung)
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
        flash('Ungültiger Dateityp. Erlaubt: PDF, PNG, JPG, JPEG, GIF', 'danger')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    try:
        # Ensure upload directory exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        filename = secure_filename(file.filename)
        if not filename:
            flash('Ungültiger Dateiname.', 'danger')
            return redirect(url_for('admin_thema_detail', task_id=task_id))

        # Add task_id to make filename unique
        filename = f"{task_id}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Save the file
        file.save(filepath)

        # Verify file was saved
        if not os.path.exists(filepath):
            raise IOError('Datei wurde nicht gespeichert.')

        # Add to database
        beschreibung = request.form.get('beschreibung', '').strip()
        models.create_material(task_id, 'datei', filename, beschreibung)

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
                'filename': material['pfad'],
                'typ': material['typ']
            }
        )

        # In production, let nginx serve the file directly (X-Accel-Redirect)
        # This frees the Python thread immediately instead of streaming bytes
        if not app.debug and request.headers.get('X-Forwarded-For'):
            import mimetypes
            content_type = mimetypes.guess_type(material['pfad'])[0] or 'application/octet-stream'
            response = Response('')
            response.headers['X-Accel-Redirect'] = f'/protected-files/{material["pfad"]}'
            response.headers['Content-Type'] = content_type
            return response

        # Development fallback: serve directly through Flask
        return send_from_directory(
            config.UPLOAD_FOLDER,
            material['pfad'],
            as_attachment=False
        )
    except PermissionError as e:
        app.logger.error(f'Download permission error: {e}')
        flash('Fehler: Keine Berechtigung zum Lesen der Datei.', 'danger')
        abort(403)
    except Exception as e:
        app.logger.error(f'Download error: {e}')
        flash('Fehler beim Laden der Datei.', 'danger')
        abort(500)


# ============ Admin: Wahlpflicht (Elective Groups) ============

@app.route('/admin/wahlpflicht')
@admin_required
def admin_wahlpflicht():
    gruppen = models.get_all_wahlpflicht_gruppen()
    tasks = models.get_all_tasks()
    # Get tasks for each group
    gruppen_tasks = {}
    for gruppe in gruppen:
        gruppen_tasks[gruppe['id']] = models.get_wahlpflicht_tasks(gruppe['id'])
    return render_template('admin/wahlpflicht.html', gruppen=gruppen, gruppen_tasks=gruppen_tasks, tasks=tasks, subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/wahlpflicht/neu', methods=['POST'])
@admin_required
def admin_wahlpflicht_neu():
    gruppe_id = models.create_wahlpflicht_gruppe(
        name=request.form['name'],
        beschreibung=request.form.get('beschreibung', ''),
        fach=request.form['fach'],
        stufe=request.form['stufe']
    )
    flash('Wahlpflichtgruppe erstellt. ✅', 'success')
    return redirect(url_for('admin_wahlpflicht'))


@app.route('/admin/wahlpflicht/<int:gruppe_id>/thema-hinzufuegen', methods=['POST'])
@admin_required
def admin_wahlpflicht_thema_hinzufuegen(gruppe_id):
    task_id = request.form.get('task_id')
    if task_id:
        models.add_task_to_wahlpflicht(gruppe_id, int(task_id))
        flash('Thema zur Gruppe hinzugefügt. ✅', 'success')
    return redirect(url_for('admin_wahlpflicht'))


@app.route('/admin/wahlpflicht/<int:gruppe_id>/thema/<int:task_id>/entfernen', methods=['POST'])
@admin_required
def admin_wahlpflicht_thema_entfernen(gruppe_id, task_id):
    models.remove_task_from_wahlpflicht(gruppe_id, task_id)
    flash('Thema aus Gruppe entfernt.', 'success')
    return redirect(url_for('admin_wahlpflicht'))


@app.route('/admin/wahlpflicht/<int:gruppe_id>/loeschen', methods=['POST'])
@admin_required
def admin_wahlpflicht_loeschen(gruppe_id):
    models.delete_wahlpflicht_gruppe(gruppe_id)
    flash('Wahlpflichtgruppe gelöscht.', 'success')
    return redirect(url_for('admin_wahlpflicht'))


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

    return render_template('admin/student_activity.html',
                         student=student,
                         events=events,
                         summary=summary,
                         page=page,
                         total_pages=total_pages,
                         total_count=total_count,
                         date_from=date_from,
                         date_to=date_to)


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
            # Count only path-required subtasks for progress
            required_subtasks = [s for s in visible_with_progress if s.get('required', True)]
            task['total_subtasks'] = len(required_subtasks)
            task['completed_subtasks'] = sum(1 for s in required_subtasks if s['erledigt'])

            # Find first incomplete subtask name for preview
            import re as _re
            next_subtask = next((s for s in visible_with_progress if not s['erledigt']), None)
            if next_subtask and next_subtask.get('beschreibung'):
                # Extract ### heading as task name, fall back to first line
                heading = _re.match(r'^#{1,4}\s+(.+)', next_subtask['beschreibung'])
                task['next_task_preview'] = heading.group(1).strip() if heading else next_subtask['beschreibung'].split('\n')[0][:80]
            else:
                task['next_task_preview'] = None
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

    # Check if practice mode has questions available
    has_warmup_pool = bool(models.get_warmup_question_pool(student_id))

    return render_template('student/dashboard.html', student=student, klassen=klassen,
                           tasks_by_klasse=tasks_by_klasse,
                           next_topics=next_topics,
                           sidequests_by_klasse=sidequests_by_klasse,
                           student_path=student.get('lernpfad'),
                           has_warmup_pool=has_warmup_pool)


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
    completed_subtasks = []
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
                current_subtask = subtasks[0]
        elif subtasks:
            # Default to first visible subtask
            current_subtask = subtasks[0]

        # Load materials filtered by current Aufgabe
        if current_subtask:
            materials = models.get_materials_for_subtask(task['task_id'], current_subtask['id'])
        else:
            materials = models.get_materials(task['task_id'])

        # Q5A: Calculate completed based on VISIBLE subtasks only
        completed_subtasks = [st for st in subtasks if st['erledigt']]

    # Check for next queued topic (only when current is completed)
    next_topic = None
    if task and task.get('abgeschlossen'):
        next_topic = models.get_next_queued_topic(klasse_id, task['task_id'])

    return render_template('student/klasse.html',
                           student=student,
                           klasse=klasse,
                           task=task,
                           subtasks=subtasks,
                           all_subtasks=all_subtasks,
                           completed_subtasks=completed_subtasks,
                           current_subtask=current_subtask,
                           materials=materials,
                           quiz_attempts=quiz_attempts,
                           subtask_quiz_status=subtask_quiz_status,
                           quiz_bestanden=quiz_bestanden,
                           next_topic=next_topic,
                           student_path=student.get('lernpfad') if student else None)


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


def _handle_quiz(student_id, student, task, slug, quiz_json_str, subtask_id=None, position=None):
    """Shared quiz logic for topic and subtask quizzes."""
    student_task_id = task['id']
    quiz = json.loads(quiz_json_str)

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

        attempt_id, bestanden = models.save_quiz_attempt(
            student_task_id, punkte, max_punkte, json.dumps(antworten), subtask_id=subtask_id
        )

        models.log_analytics_event(
            event_type='quiz_attempt',
            user_id=student_id,
            user_type='student',
            metadata={
                'student_task_id': student_task_id,
                'subtask_id': subtask_id,
                'punkte': punkte,
                'max_punkte': max_punkte,
                'bestanden': bestanden,
                'prozent': int((punkte / max_punkte) * 100) if max_punkte > 0 else 0
            }
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

        display_quiz = _build_display_quiz(quiz)

        all_attempts = models.get_quiz_attempts(student_task_id, subtask_id=subtask_id)
        previous_attempt = all_attempts[1] if len(all_attempts) > 1 else None

        return render_template('student/quiz_result.html',
                               student=student,
                               task=task,
                               quiz=display_quiz,
                               punkte=punkte,
                               max_punkte=max_punkte,
                               bestanden=bestanden,
                               antworten=antworten,
                               previous_attempt=previous_attempt,
                               slug=slug,
                               position=position)

    # GET: Filter out LLM questions if rate limit exceeded
    llm_available = models.check_llm_rate_limit(student_id)
    if not llm_available:
        quiz['questions'] = [q for q in quiz['questions'] if q.get('type', 'multiple_choice') == 'multiple_choice']
        if not quiz['questions']:
            flash('Du hast dein Quiz-Limit erreicht. Versuche es später erneut.', 'warning')
            return redirect(url_for('student_klasse', slug=slug))

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

    return _handle_quiz(student_id, student, task, slug, subtask_row['quiz_json'],
                        subtask_id=subtask['id'], position=position)


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
        flash('Noch kein Quiz-Ergebnis vorhanden.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    latest = attempts[0]
    quiz = json.loads(task['quiz_json'])
    antworten = json.loads(latest['antworten_json']) if latest['antworten_json'] else {}

    return render_template('student/quiz_result.html',
                           student=student, task=task,
                           quiz=_build_display_quiz(quiz),
                           punkte=latest['punkte'], max_punkte=latest['max_punkte'],
                           bestanden=latest['bestanden'], antworten=antworten,
                           previous_attempt=attempts[1] if len(attempts) > 1 else None,
                           slug=slug, position=None)


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
        flash('Noch kein Quiz-Ergebnis vorhanden.', 'warning')
        return redirect(url_for('student_klasse', slug=slug))

    latest = attempts[0]
    with models.db_session() as conn:
        subtask_row = conn.execute("SELECT quiz_json FROM subtask WHERE id = ?", (subtask['id'],)).fetchone()

    quiz = json.loads(subtask_row['quiz_json'])
    antworten = json.loads(latest['antworten_json']) if latest['antworten_json'] else {}

    next_position = position + 1 if position < len(subtasks) else None
    topic_quiz_attempts = models.get_quiz_attempts(task['id'])
    quiz_bestanden = any(a['bestanden'] for a in topic_quiz_attempts)

    return render_template('student/quiz_result.html',
                           student=student, task=task,
                           quiz=_build_display_quiz(quiz),
                           punkte=latest['punkte'], max_punkte=latest['max_punkte'],
                           bestanden=latest['bestanden'], antworten=antworten,
                           previous_attempt=attempts[1] if len(attempts) > 1 else None,
                           slug=slug, position=position,
                           next_position=next_position,
                           quiz_bestanden=quiz_bestanden)


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
        flash('Ungültige Anfrage.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Validate: student is in this class
    klassen = models.get_student_klassen(student_id)
    if not any(k['id'] == klasse_id for k in klassen):
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Validate: task_id is in the class queue
    queue = models.get_topic_queue(klasse_id)
    if not any(q['task_id'] == task_id for q in queue):
        flash('Thema nicht in der Reihenfolge.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Get task name for flash message and redirect
    task = models.get_task(task_id)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
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
    """Student settings page (Easy Reading Mode + Learning Path)."""
    student_id = session['student_id']

    if request.method == 'POST':
        easy_reading_mode = 1 if request.form.get('easy_reading_mode') == 'on' else 0
        models.update_student_setting(student_id, 'easy_reading_mode', easy_reading_mode)

        # Handle learning path change
        lernpfad = request.form.get('lernpfad')
        if lernpfad in ('wanderweg', 'bergweg', 'gipfeltour'):
            models.update_student_setting(student_id, 'lernpfad', lernpfad)

        flash('Einstellungen gespeichert! ✅', 'success')
        return redirect(url_for('student_settings'))

    student = models.get_student(student_id)
    return render_template('student/settings.html', student=student)


# ============ Warmup / Spaced Repetition ============

def _grade_warmup_answer(question, answer):
    """Grade a single warmup answer. Returns (correct: bool, feedback: str).

    MC: compare selected indices to correct set.
    fill_blank: case-insensitive exact match, then LLM fallback.
    """
    qtype = question.get('type', 'multiple_choice')

    if qtype == 'fill_blank':
        student_text = (answer or '').strip()
        if not student_text:
            return False, 'Keine Antwort.'
        # Exact match (case-insensitive)
        if student_text.lower() in [a.lower() for a in question['answers']]:
            return True, 'Richtig!'
        # LLM fallback
        result = llm_grading.grade_answer(
            question['text'], ', '.join(question['answers']),
            student_text, session.get('student_id')
        )
        return result['correct'], result.get('feedback', '')
    else:
        # Multiple choice
        try:
            submitted = set(int(x) for x in answer) if answer else set()
        except (ValueError, TypeError):
            submitted = set()
        correct_set = set(question.get('correct', []))
        if submitted == correct_set:
            return True, 'Richtig!'
        # Build feedback showing correct answer(s)
        options = question.get('options', [])
        correct_texts = []
        for idx in correct_set:
            if idx < len(options):
                opt = options[idx]
                correct_texts.append(opt['text'] if isinstance(opt, dict) else str(opt))
        return False, f'Richtige Antwort: {", ".join(correct_texts)}'


def _serialize_question_for_js(item):
    """Convert a pool item to a JSON-safe dict for the frontend."""
    q = item['question']
    result = {
        'task_id': item['task_id'],
        'subtask_id': item['subtask_id'],
        'question_index': item['question_index'],
        'topic_name': item['topic_name'],
        'type': q.get('type', 'multiple_choice'),
        'text': q['text'],
    }
    if result['type'] == 'fill_blank':
        # Don't send answers to client
        pass
    else:
        # MC: send options (shuffled) + correct indices
        options = q.get('options', [])
        result['options'] = options
        result['correct'] = q.get('correct', [])
    if q.get('image'):
        result['image'] = q['image']
    return result


@app.route('/schueler/aufwaermen')
@student_required
def student_warmup():
    """Warmup page — 2 easy questions, optionally 2 hard if both correct."""
    student_id = session['student_id']
    student = models.get_student(student_id)

    # Already done today? → dashboard
    if models.has_done_warmup_today(student_id):
        return redirect(url_for('student_dashboard'))

    pool = models.get_warmup_question_pool(student_id)
    if not pool:
        return redirect(url_for('student_dashboard'))

    easy_questions = models.select_warmup_questions(student_id, pool, difficulty='easy', count=2)
    if not easy_questions:
        return redirect(url_for('student_dashboard'))

    questions_json = json.dumps([_serialize_question_for_js(q) for q in easy_questions])
    return render_template('student/warmup.html', student=student,
                           questions_json=questions_json)


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
    question = None
    for item in pool:
        if (item['task_id'] == task_id and
                item['subtask_id'] == subtask_id and
                item['question_index'] == question_index):
            question = item['question']
            break

    if question is None:
        return jsonify({'error': 'Question not found'}), 404

    correct, feedback = _grade_warmup_answer(question, answer)
    models.record_warmup_answer(student_id, task_id, subtask_id, question_index, correct)

    # Build correct_answer for feedback display
    # MC: always send correct indices (needed for ✅/❌ highlighting on all options)
    # fill_blank: only send on wrong answer (shows expected answer)
    qtype = question.get('type', 'multiple_choice')
    correct_answer = None
    if qtype == 'fill_blank':
        if not correct:
            correct_answer = question['answers'][0] if question.get('answers') else None
    else:
        correct_answer = question.get('correct', [])

    return jsonify({
        'correct': correct,
        'feedback': feedback,
        'correct_answer': correct_answer
    })


@app.route('/schueler/aufwaermen/weiter', methods=['POST'])
@student_required
def student_warmup_continue():
    """AJAX: after easy round all correct, return 2 hard questions."""
    student_id = session['student_id']
    data = request.get_json() or {}

    # Exclude questions already shown in the easy round
    shown = data.get('shown', [])
    shown_keys = set()
    for s in shown:
        shown_keys.add((s.get('task_id'), s.get('subtask_id'), s.get('question_index')))

    pool = models.get_warmup_question_pool(student_id)
    pool = [q for q in pool
            if (q['task_id'], q['subtask_id'], q['question_index']) not in shown_keys]

    hard_questions = models.select_warmup_questions(student_id, pool, difficulty='hard', count=2)

    if not hard_questions:
        return jsonify({'done': True})

    return jsonify({
        'done': False,
        'questions': [_serialize_question_for_js(q) for q in hard_questions]
    })


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
        skipped=data.get('skipped', False)
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

    # Select questions based on mode
    if mode == 'schwaechen':
        questions = models.select_warmup_questions(student_id, pool, difficulty='hard', count=5)
    else:
        questions = models.select_warmup_questions(student_id, pool, difficulty='mixed', count=5)

    if not questions:
        flash('Keine passenden Fragen gefunden.', 'info')
        return redirect(url_for('student_practice', mode='random'))

    questions_json = json.dumps([_serialize_question_for_js(q) for q in questions])
    return render_template('student/practice.html', student=student,
                           questions_json=questions_json, mode=mode,
                           topic_names=topic_names, selected_topic=topic_slug)


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
    flash('Ungültige Anfrage.', 'warning')
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
    flash('Ein unerwarteter Fehler ist aufgetreten. Der Fehler wurde protokolliert.', 'danger')
    return redirect(url_for('index'))


# ============ Analytics Middleware ============

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
    print(f"Page view logging: {'enabled' if app.config['LOG_PAGE_VIEWS'] else 'disabled'}")

    # Create default admin if not exists
    if models.create_admin('admin', 'admin'):
        print("Default admin created: admin/admin")


if __name__ == '__main__':
    init_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
