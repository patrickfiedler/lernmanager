import os
import json
from functools import wraps
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename

import config
import models
from utils import generate_username, generate_password, allowed_file
app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH


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
            flash('Willkommen zurück! 👋', 'success')
            return redirect(url_for('admin_dashboard'))

        # Try student login
        student = models.verify_student(username, password)
        if student:
            session['student_id'] = student['id']
            session['student_name'] = f"{student['vorname']} {student['nachname']}"
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
    return render_template('admin/dashboard.html', klassen=klassen, tasks=tasks)


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
    return render_template('admin/klasse_detail.html', klasse=klasse, students=students, tasks=tasks, unterricht=unterricht)


@app.route('/admin/klasse/<int:klasse_id>/loeschen', methods=['POST'])
@admin_required
def admin_klasse_loeschen(klasse_id):
    klasse = models.get_klasse(klasse_id)
    if klasse:
        models.delete_klasse(klasse_id)
        flash(f'Klasse "{klasse["name"]}" gelöscht.', 'success')
    return redirect(url_for('admin_klassen'))


@app.route('/admin/klasse/<int:klasse_id>/schueler-hinzufuegen', methods=['POST'])
@admin_required
def admin_klasse_schueler_hinzufuegen(klasse_id):
    batch_input = request.form['batch_input']
    existing_usernames = models.get_existing_usernames()

    added = 0
    for line in batch_input.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) >= 2:
            nachname = parts[0].strip()
            vorname = parts[1].strip()

            username = generate_username(existing_usernames)
            existing_usernames.add(username)
            password = generate_password()

            student_id = models.create_student(nachname, vorname, username, password)
            models.add_student_to_klasse(student_id, klasse_id)
            added += 1

    flash(f'{added} Schüler hinzugefügt. ✅', 'success')
    return redirect(url_for('admin_klasse_detail', klasse_id=klasse_id))


@app.route('/admin/klasse/<int:klasse_id>/aufgabe-zuweisen', methods=['POST'])
@admin_required
def admin_klasse_aufgabe_zuweisen(klasse_id):
    task_id = request.form['task_id']
    if task_id:
        models.assign_task_to_klasse(klasse_id, int(task_id))
        flash('Aufgabe für alle Schüler zugewiesen. ✅', 'success')
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
    return render_template('admin/schueler_detail.html', student=student, klassen=klassen, all_klassen=all_klassen, tasks=tasks)


@app.route('/admin/schueler/<int:student_id>/loeschen', methods=['POST'])
@admin_required
def admin_schueler_loeschen(student_id):
    models.delete_student(student_id)
    flash('Schüler gelöscht.', 'success')
    return redirect(request.referrer or url_for('admin_klassen'))


@app.route('/admin/schueler/<int:student_id>/verschieben', methods=['POST'])
@admin_required
def admin_schueler_verschieben(student_id):
    from_klasse = request.form['from_klasse']
    to_klasse = request.form['to_klasse']
    if from_klasse and to_klasse:
        models.move_student_to_klasse(student_id, int(from_klasse), int(to_klasse))
        flash('Schüler verschoben. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/aufgabe-zuweisen', methods=['POST'])
@admin_required
def admin_schueler_aufgabe_zuweisen(student_id):
    klasse_id = request.form['klasse_id']
    task_id = request.form['task_id']
    if klasse_id and task_id:
        models.assign_task_to_student(student_id, int(klasse_id), int(task_id))
        flash('Aufgabe zugewiesen. ✅', 'success')
    return redirect(url_for('admin_schueler_detail', student_id=student_id))


@app.route('/admin/schueler/<int:student_id>/klasse/<int:klasse_id>/abschliessen', methods=['POST'])
@admin_required
def admin_schueler_aufgabe_abschliessen(student_id, klasse_id):
    student_task = models.get_student_task(student_id, klasse_id)
    if student_task:
        models.mark_task_complete(student_task['id'], manual=True)
        flash('Aufgabe manuell abgeschlossen. ✅', 'success')
    return redirect(request.referrer or url_for('admin_schueler_detail', student_id=student_id))


# ============ Admin: Tasks ============

@app.route('/admin/aufgaben')
@admin_required
def admin_aufgaben():
    tasks = models.get_all_tasks()
    return render_template('admin/aufgaben.html', tasks=tasks, subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/aufgabe/neu', methods=['GET', 'POST'])
@admin_required
def admin_aufgabe_neu():
    if request.method == 'POST':
        task_id = models.create_task(
            name=request.form['name'],
            beschreibung=request.form['beschreibung'],
            lernziel=request.form['lernziel'],
            fach=request.form['fach'],
            stufe=request.form['stufe'],
            kategorie=request.form['kategorie'],
            voraussetzung_id=request.form.get('voraussetzung_id') or None
        )
        flash(f'Aufgabe erstellt. ✅', 'success')
        return redirect(url_for('admin_aufgabe_detail', task_id=task_id))

    tasks = models.get_all_tasks()
    return render_template('admin/aufgabe_form.html', task=None, tasks=tasks, subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/aufgabe/<int:task_id>')
@admin_required
def admin_aufgabe_detail(task_id):
    task = models.get_task(task_id)
    if not task:
        flash('Aufgabe nicht gefunden.', 'danger')
        return redirect(url_for('admin_aufgaben'))
    subtasks = models.get_subtasks(task_id)
    materials = models.get_materials(task_id)
    all_tasks = models.get_all_tasks()
    return render_template('admin/aufgabe_detail.html', task=task, subtasks=subtasks, materials=materials, all_tasks=all_tasks, subjects=config.SUBJECTS, levels=config.LEVELS)


@app.route('/admin/aufgabe/<int:task_id>/bearbeiten', methods=['POST'])
@admin_required
def admin_aufgabe_bearbeiten(task_id):
    models.update_task(
        task_id=task_id,
        name=request.form['name'],
        beschreibung=request.form['beschreibung'],
        lernziel=request.form['lernziel'],
        fach=request.form['fach'],
        stufe=request.form['stufe'],
        kategorie=request.form['kategorie'],
        voraussetzung_id=request.form.get('voraussetzung_id') or None,
        quiz_json=request.form.get('quiz_json') or None
    )
    flash('Aufgabe aktualisiert. ✅', 'success')
    return redirect(url_for('admin_aufgabe_detail', task_id=task_id))


@app.route('/admin/aufgabe/<int:task_id>/loeschen', methods=['POST'])
@admin_required
def admin_aufgabe_loeschen(task_id):
    models.delete_task(task_id)
    flash('Aufgabe gelöscht.', 'success')
    return redirect(url_for('admin_aufgaben'))


@app.route('/admin/aufgabe/<int:task_id>/teilaufgaben', methods=['POST'])
@admin_required
def admin_aufgabe_teilaufgaben(task_id):
    subtasks_text = request.form['subtasks']
    subtasks_list = subtasks_text.strip().split('\n')
    models.update_subtasks(task_id, subtasks_list)
    flash('Teilaufgaben aktualisiert. ✅', 'success')
    return redirect(url_for('admin_aufgabe_detail', task_id=task_id))


@app.route('/admin/aufgabe/<int:task_id>/material-link', methods=['POST'])
@admin_required
def admin_aufgabe_material_link(task_id):
    url = request.form['url'].strip()
    beschreibung = request.form.get('beschreibung', '').strip()
    if url:
        models.create_material(task_id, 'link', url, beschreibung)
        flash('Link hinzugefügt. ✅', 'success')
    return redirect(url_for('admin_aufgabe_detail', task_id=task_id))


@app.route('/admin/aufgabe/<int:task_id>/material-upload', methods=['POST'])
@admin_required
def admin_aufgabe_material_upload(task_id):
    if 'file' not in request.files:
        flash('Keine Datei ausgewählt.', 'warning')
        return redirect(url_for('admin_aufgabe_detail', task_id=task_id))

    file = request.files['file']
    if file.filename == '':
        flash('Keine Datei ausgewählt.', 'warning')
        return redirect(url_for('admin_aufgabe_detail', task_id=task_id))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add task_id to make filename unique
        filename = f"{task_id}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        beschreibung = request.form.get('beschreibung', '').strip()
        models.create_material(task_id, 'datei', filename, beschreibung)
        flash('Datei hochgeladen. ✅', 'success')
    else:
        flash('Ungültiger Dateityp.', 'danger')

    return redirect(url_for('admin_aufgabe_detail', task_id=task_id))


@app.route('/admin/material/<int:material_id>/loeschen', methods=['POST'])
@admin_required
def admin_material_loeschen(material_id):
    models.delete_material(material_id)
    flash('Material gelöscht.', 'success')
    return redirect(request.referrer or url_for('admin_aufgaben'))


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
        students = conn.execute('''
            SELECT us.*, s.nachname, s.vorname
            FROM unterricht_student us
            JOIN student s ON us.student_id = s.id
            WHERE us.unterricht_id = ?
            ORDER BY s.nachname, s.vorname
        ''', (unterricht_id,)).fetchall()
        students = [dict(s) for s in students]

    return render_template('admin/unterricht.html', klasse=klasse, datum=datum, unterricht_id=unterricht_id, students=students)


@app.route('/admin/unterricht/<int:unterricht_id>/bewertung', methods=['POST'])
@admin_required
def admin_unterricht_bewertung(unterricht_id):
    student_id = request.form['student_id']
    anwesend = 1 if request.form.get('anwesend') else 0
    admin_selbst = int(request.form.get('admin_selbststaendigkeit', 2))
    admin_respekt = int(request.form.get('admin_respekt', 2))
    admin_fortschritt = int(request.form.get('admin_fortschritt', 2))
    admin_kommentar = request.form.get('admin_kommentar', '')

    models.update_unterricht_student(
        unterricht_id, int(student_id),
        anwesend, admin_selbst, admin_respekt, admin_fortschritt, admin_kommentar
    )

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
            subtasks = models.get_student_subtask_progress(task['id'])
            task['subtasks'] = subtasks
            task['total_subtasks'] = len(subtasks)
            task['completed_subtasks'] = sum(1 for s in subtasks if s['erledigt'])
        tasks_by_klasse[klasse['id']] = task

    return render_template('student/dashboard.html', student=student, klassen=klassen,
                           tasks_by_klasse=tasks_by_klasse)


@app.route('/schueler/klasse/<int:klasse_id>')
@student_required
def student_klasse(klasse_id):
    student_id = session['student_id']
    klasse = models.get_klasse(klasse_id)
    if not klasse:
        flash('Klasse nicht gefunden.', 'danger')
        return redirect(url_for('student_dashboard'))

    task = models.get_student_task(student_id, klasse_id)
    subtasks = []
    materials = []
    quiz_attempts = []

    if task:
        subtasks = models.get_student_subtask_progress(task['id'])
        materials = models.get_materials(task['task_id'])
        quiz_attempts = models.get_quiz_attempts(task['id'])

    # Get lesson history
    unterricht = models.get_student_unterricht(student_id, klasse_id)

    return render_template('student/klasse.html',
                           klasse=klasse,
                           task=task,
                           subtasks=subtasks,
                           materials=materials,
                           quiz_attempts=quiz_attempts,
                           unterricht=unterricht)


@app.route('/schueler/aufgabe/<int:student_task_id>/teilaufgabe/<int:subtask_id>', methods=['POST'])
@student_required
def student_toggle_subtask(student_task_id, subtask_id):
    erledigt = request.json.get('erledigt', False)
    models.toggle_student_subtask(student_task_id, subtask_id, erledigt)

    # Check if task should be auto-completed
    if models.check_task_completion(student_task_id):
        models.mark_task_complete(student_task_id)
        return jsonify({'status': 'ok', 'task_complete': True})

    return jsonify({'status': 'ok', 'task_complete': False})


@app.route('/schueler/aufgabe/<int:student_task_id>/quiz', methods=['GET', 'POST'])
@student_required
def student_quiz(student_task_id):
    student_id = session['student_id']

    with models.db_session() as conn:
        # Verify this task belongs to the student
        task_row = conn.execute('''
            SELECT st.*, t.name, t.quiz_json
            FROM student_task st
            JOIN task t ON st.task_id = t.id
            WHERE st.id = ? AND st.student_id = ?
        ''', (student_task_id, student_id)).fetchone()

        if not task_row:
            flash('Aufgabe nicht gefunden.', 'danger')
            return redirect(url_for('student_dashboard'))

        task = dict(task_row)

    if not task['quiz_json']:
        flash('Diese Aufgabe hat kein Quiz.', 'warning')
        return redirect(url_for('student_dashboard'))

    quiz = json.loads(task['quiz_json'])

    if request.method == 'POST':
        # Grade the quiz
        punkte = 0
        max_punkte = len(quiz['questions'])
        antworten = {}

        for i, question in enumerate(quiz['questions']):
            submitted = request.form.getlist(f'q{i}')
            submitted_indices = [int(x) for x in submitted]
            correct = question['correct']

            antworten[str(i)] = submitted_indices

            # Check if answer is correct (all correct options selected, no incorrect ones)
            if set(submitted_indices) == set(correct):
                punkte += 1

        attempt_id, bestanden = models.save_quiz_attempt(
            student_task_id, punkte, max_punkte, json.dumps(antworten)
        )

        # Check task completion
        if models.check_task_completion(student_task_id):
            models.mark_task_complete(student_task_id)

        return render_template('student/quiz_result.html',
                               task=task,
                               quiz=quiz,
                               punkte=punkte,
                               max_punkte=max_punkte,
                               bestanden=bestanden,
                               antworten=antworten)

    return render_template('student/quiz.html', task=task, quiz=quiz, student_task_id=student_task_id)


@app.route('/schueler/unterricht/<int:unterricht_id>/selbstbewertung', methods=['POST'])
@student_required
def student_selbstbewertung(unterricht_id):
    student_id = session['student_id']
    selbst_selbst = int(request.form.get('selbst_selbststaendigkeit', 2))
    selbst_respekt = int(request.form.get('selbst_respekt', 2))

    models.update_student_self_eval(unterricht_id, student_id, selbst_selbst, selbst_respekt)
    flash('Selbstbewertung gespeichert. ✅', 'success')
    return redirect(request.referrer or url_for('student_dashboard'))


# ============ Initialize ============

def init_app():
    """Initialize the application."""
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.dirname(config.DATABASE), exist_ok=True)
    models.init_db()

    # Create default admin if not exists
    if models.create_admin('admin', 'admin'):
        print("Default admin created: admin/admin")


if __name__ == '__main__':
    init_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
