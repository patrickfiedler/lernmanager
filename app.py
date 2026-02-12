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
from utils import generate_username, generate_password, allowed_file, generate_credentials_pdf, generate_student_self_report_pdf

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
            return redirect(url_for('student_dashboard'))

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
    return render_template('admin/klasse_detail.html', klasse=klasse, students=students, tasks=tasks, unterricht=unterricht, schedule=schedule)


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
    subtask_id = request.form.get('subtask_id')
    if task_id:
        # Convert to int, handle empty string for subtask_id
        subtask_id_int = int(subtask_id) if subtask_id and subtask_id.strip() else None
        models.assign_task_to_klasse(klasse_id, int(task_id), subtask_id_int, admin_id=session['admin_id'])

        # Q1A: Interrupt workflow - redirect to subtask configuration
        flash('Thema zugewiesen. Bitte wähle nun die sichtbaren Aufgaben. ✅', 'success')
        return redirect(url_for('admin_aufgaben_verwaltung_klasse', klasse_id=klasse_id, task_id=task_id))

    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


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
        task = models.get_student_task(student_id, klasse['id'])
        if task:
            # Get all subtasks and current subtask
            subtasks = models.get_student_subtask_progress(task['id'])
            task['subtasks'] = subtasks
            current_subtask = models.get_current_subtask(task['id'])
            task['current_subtask'] = current_subtask
        student_tasks[klasse['id']] = task

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
    subtask_id = request.form.get('subtask_id')
    if klasse_id and task_id:
        # Convert to int, handle empty string for subtask_id
        subtask_id_int = int(subtask_id) if subtask_id and subtask_id.strip() else None
        models.assign_task_to_student(student_id, int(klasse_id), int(task_id), subtask_id_int, admin_id=session['admin_id'])
        if subtask_id_int:
            flash('Thema und Aufgabe zugewiesen. ✅', 'success')
        else:
            flash('Thema zugewiesen. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/aufgabe-setzen', methods=['POST'])
@admin_required
def admin_schueler_aufgabe_setzen(student_id):
    """Update the current subtask for a student's task."""
    klasse_id = request.form['klasse_id']
    subtask_id = request.form.get('subtask_id')

    if klasse_id:
        student_task = models.get_student_task(student_id, int(klasse_id))
        if student_task:
            # Convert to int, handle empty string for subtask_id
            subtask_id_int = int(subtask_id) if subtask_id and subtask_id.strip() else None
            models.set_current_subtask(student_task['id'], subtask_id_int)
            if subtask_id_int:
                flash('Aktuelle Aufgabe aktualisiert. ✅', 'success')
            else:
                flash('Aufgaben-Filter entfernt (alle Aufgaben sichtbar). ✅', 'success')
        else:
            flash('Schüler hat kein Thema in dieser Klasse.', 'warning')
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
    # Get prerequisites for each task
    task_voraussetzungen = {}
    for task in tasks:
        task_voraussetzungen[task['id']] = models.get_task_voraussetzungen(task['id'])
    return render_template('admin/aufgaben.html', tasks=tasks, task_voraussetzungen=task_voraussetzungen, subjects=config.SUBJECTS, levels=config.LEVELS)


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
            why_learn_this=request.form.get('why_learn_this') or None
        )
        # Handle multiple prerequisites
        voraussetzung_ids = request.form.getlist('voraussetzungen')
        if voraussetzung_ids:
            models.set_task_voraussetzungen(task_id, [int(v) for v in voraussetzung_ids if v])
        flash('Thema erstellt. ✅', 'success')
        return redirect(url_for('admin_thema_detail', task_id=task_id))

    tasks = models.get_all_tasks()
    return render_template('admin/aufgabe_form.html', task=None, tasks=tasks, voraussetzungen=[], subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/thema/<int:task_id>')
@admin_required
def admin_thema_detail(task_id):
    task = models.get_task(task_id)
    if not task:
        flash('Thema nicht gefunden.', 'danger')
        return redirect(url_for('admin_themen'))
    subtasks = models.get_subtasks(task_id)
    materials = models.get_materials(task_id)
    all_tasks = models.get_all_tasks()
    voraussetzungen = models.get_task_voraussetzungen(task_id)
    return render_template('admin/aufgabe_detail.html', task=task, subtasks=subtasks, materials=materials, all_tasks=all_tasks, voraussetzungen=voraussetzungen, subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/thema/<int:task_id>/bearbeiten', methods=['POST'])
@admin_required
def admin_thema_bearbeiten(task_id):
    models.update_task(
        task_id=task_id,
        name=request.form['name'],
        beschreibung=request.form['beschreibung'],
        lernziel=request.form['lernziel'],
        fach=request.form['fach'],
        stufe=request.form['stufe'],
        kategorie=request.form['kategorie'],
        quiz_json=request.form.get('quiz_json') or None,
        number=int(request.form.get('number', 0)),
        why_learn_this=request.form.get('why_learn_this') or None,
        subtask_quiz_required=1 if request.form.get('subtask_quiz_required') else 0
    )
    # Handle multiple prerequisites
    voraussetzung_ids = request.form.getlist('voraussetzungen')
    models.set_task_voraussetzungen(task_id, [int(v) for v in voraussetzung_ids if v])
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
        # POST: update subtasks (includes time estimates and per-subtask quizzes)
        subtasks_list = request.form.getlist('subtasks[]')
        estimated_minutes_list = request.form.getlist('estimated_minutes[]')
        quiz_json_list = request.form.getlist('quiz_json[]')
        models.update_subtasks(task_id, subtasks_list, estimated_minutes_list, quiz_json_list)
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


# ============ Admin: Teilaufgaben-Verwaltung (Subtask Visibility) ============

@app.route('/admin/aufgaben-verwaltung/klasse/<int:klasse_id>')
@admin_required
def admin_aufgaben_verwaltung_klasse(klasse_id):
    """Manage subtask visibility for a class.

    Implements Q1A (interrupt workflow) and Q2B (two-column UI).
    """
    task_id = request.args.get('task_id', type=int)
    if not task_id:
        flash('Kein Thema ausgewählt.', 'danger')
        return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))

    # Get class and task info
    klasse = models.get_klasse(klasse_id)
    task = models.get_task(task_id)
    if not klasse or not task:
        flash('Klasse oder Thema nicht gefunden.', 'danger')
        return redirect(url_for('admin_klassen'))

    # Get all subtasks for this task
    subtasks = models.get_subtasks(task_id)

    # Get current visibility settings for this class
    visibility = models.get_subtask_visibility_settings(klasse_id=klasse_id, task_id=task_id)

    return render_template('admin/teilaufgaben_verwaltung.html',
                           context='class',
                           klasse=klasse,
                           task=task,
                           subtasks=subtasks,
                           visibility=visibility)


@app.route('/admin/aufgaben-verwaltung/schueler/<int:student_id>')
@admin_required
def admin_aufgaben_verwaltung_schueler(student_id):
    """Manage subtask visibility for an individual student.

    Implements Q2B (two-column UI showing class vs student settings).
    """
    try:
        task_id = request.args.get('task_id', type=int)
        klasse_id = request.args.get('klasse_id', type=int)

        print(f"DEBUG: student_id={student_id}, task_id={task_id}, klasse_id={klasse_id}", flush=True)

        if not task_id or not klasse_id:
            flash('Thema oder Klasse nicht angegeben.', 'danger')
            return redirect(url_for('admin_schueler_detail', student_id=student_id))

        # Get student, class, and task info
        student = models.get_student(student_id)
        klasse = models.get_klasse(klasse_id)
        task = models.get_task(task_id)

        print(f"DEBUG: student={student}, klasse={klasse}, task={task}", flush=True)

        if not student or not klasse or not task:
            flash('Schüler, Klasse oder Thema nicht gefunden.', 'danger')
            return redirect(url_for('admin_schueler_detail', student_id=student_id))

        # Get all subtasks for this task
        subtasks = models.get_subtasks(task_id)
        print(f"DEBUG: subtasks count={len(subtasks)}", flush=True)

        # Get class visibility settings (for left column - Q2B)
        class_visibility = models.get_subtask_visibility_settings(klasse_id=klasse_id, task_id=task_id)
        print(f"DEBUG: class_visibility={class_visibility}", flush=True)

        # Get student visibility settings (for right column - Q2B)
        student_visibility = models.get_subtask_visibility_settings(student_id=student_id, task_id=task_id)
        print(f"DEBUG: student_visibility={student_visibility}", flush=True)

        return render_template('admin/teilaufgaben_verwaltung.html',
                               context='student',
                               student=student,
                               klasse=klasse,
                               task=task,
                               subtasks=subtasks,
                               class_visibility=class_visibility,
                               student_visibility=student_visibility)
    except Exception as e:
        print(f"ERROR in admin_aufgaben_verwaltung_schueler: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise


@app.route('/admin/aufgaben-verwaltung/speichern', methods=['POST'])
@admin_required
def admin_aufgaben_verwaltung_speichern():
    """Save subtask visibility settings.

    Handles both class-wide and student-specific settings.
    Implements Q4B (enable current only - receives explicit list from UI).
    """
    data = request.get_json()

    context = data.get('context')  # 'class' or 'student'
    klasse_id = data.get('klasse_id')
    student_id = data.get('student_id')
    task_id = data.get('task_id')
    subtask_settings = data.get('subtask_settings', {})  # {subtask_id: enabled}

    admin_id = session.get('admin_id')

    try:
        if context == 'class':
            # Save class-wide settings
            for subtask_id_str, enabled in subtask_settings.items():
                subtask_id = int(subtask_id_str)
                models.set_subtask_visibility_for_class(klasse_id, subtask_id, enabled, admin_id)

            return jsonify({'success': True, 'message': 'Einstellungen für die Klasse gespeichert.'})

        elif context == 'student':
            # Save student-specific overrides (only when different from class default)
            # First, get class visibility settings to compare
            class_visibility = models.get_subtask_visibility_settings(klasse_id=klasse_id, task_id=task_id)

            print(f"DEBUG SAVE: Received subtask_settings={subtask_settings}", flush=True)
            print(f"DEBUG SAVE: class_visibility={class_visibility}", flush=True)

            with models.db_session() as conn:
                for subtask_id_str, enabled in subtask_settings.items():
                    subtask_id = int(subtask_id_str)
                    class_enabled = class_visibility.get(subtask_id, {}).get('enabled', False)

                    if enabled == class_enabled:
                        # Matches class default - remove any student override
                        conn.execute('''
                            DELETE FROM subtask_visibility
                            WHERE student_id = ? AND subtask_id = ?
                        ''', (student_id, subtask_id))
                    else:
                        # Differs from class default - create/update student override
                        # Delete existing first
                        conn.execute('''
                            DELETE FROM subtask_visibility
                            WHERE student_id = ? AND subtask_id = ?
                        ''', (student_id, subtask_id))
                        # Insert new override
                        conn.execute('''
                            INSERT INTO subtask_visibility (subtask_id, student_id, enabled, set_by_admin_id)
                            VALUES (?, ?, ?, ?)
                        ''', (subtask_id, student_id, 1 if enabled else 0, admin_id))

            return jsonify({'success': True, 'message': 'Einstellungen für den Schüler gespeichert.'})

        else:
            return jsonify({'success': False, 'message': 'Ungültiger Kontext.'}), 400

    except Exception as e:
        return jsonify({'success': False, 'message': f'Fehler beim Speichern: {str(e)}'}), 500


@app.route('/admin/aufgaben-verwaltung/reset-to-class', methods=['POST'])
@admin_required
def admin_aufgaben_verwaltung_reset():
    """Reset student-specific overrides to class defaults."""
    data = request.get_json()

    student_id = data.get('student_id')
    task_id = data.get('task_id')

    try:
        models.reset_subtask_visibility_to_class_default(student_id, task_id)
        return jsonify({'success': True, 'message': 'Auf Klassenstandard zurückgesetzt.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Fehler: {str(e)}'}), 500


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
            task['total_subtasks'] = len(visible_with_progress)
            task['completed_subtasks'] = sum(1 for s in visible_with_progress if s['erledigt'])
        tasks_by_klasse[klasse['id']] = task

    return render_template('student/dashboard.html', student=student, klassen=klassen,
                           tasks_by_klasse=tasks_by_klasse)


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


@app.route('/schueler/klasse/<int:klasse_id>')
@student_required
def student_klasse(klasse_id):
    student_id = session['student_id']
    student = models.get_student(student_id)

    # Authorization: verify student is in this class
    if not models.is_student_in_klasse(student_id, klasse_id):
        flash('Zugriff verweigert.', 'danger')
        return redirect(url_for('student_dashboard'))

    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    task = models.get_student_task(student_id, klasse_id)
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
        materials = models.get_materials(task['task_id'])
        quiz_attempts = models.get_quiz_attempts(task['id'])  # topic-level only (subtask_id IS NULL)

        # Check if topic quiz was passed
        quiz_bestanden = any(a['bestanden'] for a in quiz_attempts)

        # Compute subtask quiz pass status for progress dots
        for st in all_subtasks:
            if st.get('quiz_json'):
                subtask_quiz_status[st['id']] = models.has_passed_subtask_quiz(task['id'], st['id'])

        # NEW: Get visible subtasks based on visibility rules (Q5A, Q6A)
        visible_subtask_ids = [s['id'] for s in models.get_visible_subtasks_for_student(
            student_id, klasse_id, task['task_id']
        )]

        # Filter all_subtasks to only visible ones
        if visible_subtask_ids:
            # Show only visible subtasks
            subtasks = [st for st in all_subtasks if st['id'] in visible_subtask_ids]
        else:
            # Q3B: Empty state - no subtasks enabled
            # Template will show encouraging message
            subtasks = []

        # Check if specific subtask requested via URL parameter
        requested_subtask_id = request.args.get('subtask_id', type=int)
        if requested_subtask_id and requested_subtask_id in visible_subtask_ids:
            # Find and set current subtask if it's visible
            for st in subtasks:
                if st['id'] == requested_subtask_id:
                    current_subtask = st
                    break
        elif subtasks:
            # Default to first visible subtask
            current_subtask = subtasks[0]

        # Q5A: Calculate completed based on VISIBLE subtasks only
        completed_subtasks = [st for st in subtasks if st['erledigt']]

    # Get lesson history
    unterricht = models.get_student_unterricht(student_id, klasse_id)

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
                           unterricht=unterricht,
                           subtask_quiz_status=subtask_quiz_status,
                           quiz_bestanden=quiz_bestanden)


@app.route('/schueler/thema/<int:student_task_id>/aufgabe/<int:subtask_id>', methods=['POST'])
@student_required
def student_toggle_subtask(student_task_id, subtask_id):
    student_id = session['student_id']

    # Authorization: verify this task belongs to the student
    if not models.is_student_task_owner(student_id, student_task_id):
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403

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
        quiz_url = url_for('student_quiz', student_task_id=student_task_id, subtask_id=subtask_id)
        return jsonify({'status': 'ok', 'task_complete': False, 'show_quiz': True, 'quiz_url': quiz_url})

    # Check if task should be auto-completed
    if models.check_task_completion(student_task_id):
        models.mark_task_complete(student_task_id)
        # Log task completion
        models.log_analytics_event(
            event_type='task_complete',
            user_id=student_id,
            user_type='student',
            metadata={'student_task_id': student_task_id}
        )
        return jsonify({'status': 'ok', 'task_complete': True})

    return jsonify({'status': 'ok', 'task_complete': False})


@app.route('/schueler/thema/<int:student_task_id>/quiz', methods=['GET', 'POST'])
@app.route('/schueler/thema/<int:student_task_id>/aufgabe-quiz/<int:subtask_id>', methods=['GET', 'POST'])
@student_required
def student_quiz(student_task_id, subtask_id=None):
    student_id = session['student_id']
    student = models.get_student(student_id)

    with models.db_session() as conn:
        # Verify this task belongs to the student
        task_row = conn.execute('''
            SELECT st.*, t.name, t.quiz_json, st.klasse_id
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.id = ? AND st.student_id = ?
        ''', (student_task_id, student_id)).fetchone()

        if not task_row:
            flash('Thema nicht gefunden.', 'danger')
            return redirect(url_for('student_dashboard'))

        task = dict(task_row)
        klasse_id = task['klasse_id']

        # Load quiz JSON: from subtask or from topic
        if subtask_id:
            subtask_row = conn.execute(
                "SELECT quiz_json FROM subtask WHERE id = ?", (subtask_id,)
            ).fetchone()
            if not subtask_row or not subtask_row['quiz_json']:
                flash('Diese Aufgabe hat kein Quiz.', 'warning')
                return redirect(url_for('student_klasse', klasse_id=klasse_id))
            quiz_json_str = subtask_row['quiz_json']
        else:
            if not task['quiz_json']:
                flash('Dieses Thema hat kein Quiz.', 'warning')
                return redirect(url_for('student_dashboard'))
            quiz_json_str = task['quiz_json']

    quiz = json.loads(quiz_json_str)

    if request.method == 'POST':
        # Grade the quiz using the mapping from hidden fields
        punkte = 0
        max_punkte = len(quiz['questions'])
        antworten = {}

        # Get the question order mapping (shuffled index -> original index)
        question_order = json.loads(request.form.get('question_order', '[]'))

        for shuffled_idx in range(len(quiz['questions'])):
            # Map shuffled question index to original
            original_q_idx = question_order[shuffled_idx] if question_order else shuffled_idx
            question = quiz['questions'][original_q_idx]

            # Get answer mapping for this question (shuffled answer index -> original answer index)
            answer_map = json.loads(request.form.get(f'answer_map_{shuffled_idx}', '[]'))

            # Get submitted answers (these are shuffled indices)
            submitted = request.form.getlist(f'q{shuffled_idx}')
            submitted_shuffled = [int(x) for x in submitted]

            # Map submitted shuffled indices back to original indices
            submitted_original = [answer_map[i] for i in submitted_shuffled] if answer_map else submitted_shuffled

            correct = question['correct']
            antworten[str(original_q_idx)] = submitted_original

            # Check if answer is correct (all correct options selected, no incorrect ones)
            if set(submitted_original) == set(correct):
                punkte += 1

        attempt_id, bestanden = models.save_quiz_attempt(
            student_task_id, punkte, max_punkte, json.dumps(antworten), subtask_id=subtask_id
        )

        # Log quiz attempt
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

        # After passing subtask quiz: advance to next subtask + check completion
        if subtask_id and bestanden:
            models.advance_to_next_subtask(student_task_id, subtask_id)

        # Check task completion
        if models.check_task_completion(student_task_id):
            models.mark_task_complete(student_task_id)
            # Log task completion
            models.log_analytics_event(
                event_type='task_complete',
                user_id=student_id,
                user_type='student',
                metadata={'student_task_id': student_task_id}
            )

        # Transform quiz for display (JSON uses 'text'/'options', template expects 'question'/'answers')
        display_quiz = {
            'questions': [
                {
                    'question': q['text'],
                    'answers': q['options'],
                    'correct': q['correct'],
                    'image': q.get('image')
                }
                for q in quiz['questions']
            ]
        }

        # Get previous quiz attempts for improvement tracking (UX Tier 1)
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
                               subtask_id=subtask_id,
                               klasse_id=klasse_id)

    # GET: Shuffle questions and answers for display
    import random as quiz_random

    # Create shuffled question order (list of original indices in shuffled order)
    question_order = list(range(len(quiz['questions'])))
    quiz_random.shuffle(question_order)

    # Build shuffled quiz with answer mappings
    shuffled_questions = []
    answer_maps = []  # For each question: list mapping shuffled index -> original index

    for original_idx in question_order:
        q = quiz['questions'][original_idx]

        # Create shuffled answer order (JSON uses 'options' for answers)
        options = q['options']
        answer_order = list(range(len(options)))
        quiz_random.shuffle(answer_order)
        answer_maps.append(answer_order)

        # Build shuffled question (template expects 'question' and 'answers')
        shuffled_q = {
            'question': q['text'],
            'answers': [options[i] for i in answer_order],
            'correct': q['correct'],  # Keep original for reference (not used in template)
            'image': q.get('image')
        }
        shuffled_questions.append(shuffled_q)

    shuffled_quiz = {'questions': shuffled_questions}

    return render_template('student/quiz.html',
                           student=student,
                           task=task,
                           quiz=shuffled_quiz,
                           student_task_id=student_task_id,
                           question_order=json.dumps(question_order),
                           answer_maps=[json.dumps(m) for m in answer_maps],
                           subtask_id=subtask_id,
                           klasse_id=klasse_id)


@app.route('/schueler/unterricht/<int:unterricht_id>/selbstbewertung', methods=['POST'])
@student_required
def student_selbstbewertung(unterricht_id):
    student_id = session['student_id']
    selbst_selbst = int(request.form.get('selbst_selbststaendigkeit', 2))
    selbst_respekt = int(request.form.get('selbst_respekt', 2))

    models.update_student_self_eval(unterricht_id, student_id, selbst_selbst, selbst_respekt)
    flash('Selbstbewertung gespeichert. ✅', 'success')
    return redirect(request.referrer or url_for('student_dashboard'))


@app.route('/schueler/einstellungen', methods=['GET', 'POST'])
@student_required
def student_settings():
    """Student settings page (UX Tier 1: Easy Reading Mode toggle)."""
    student_id = session['student_id']

    if request.method == 'POST':
        easy_reading_mode = 1 if request.form.get('easy_reading_mode') == 'on' else 0
        models.update_student_setting(student_id, 'easy_reading_mode', easy_reading_mode)
        flash('Einstellungen gespeichert! ✅', 'success')
        return redirect(url_for('student_settings'))

    student = models.get_student(student_id)
    return render_template('student/settings.html', student=student)


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
    models.migrate_add_current_subtask()

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
