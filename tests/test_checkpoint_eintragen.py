"""Phase 3: teacher's 0/2/3 for Abnahme/Artefakt, per section (chemie docs/32 § 3).

Sections (`abschnitte`) come with fixed ids from the import; each counts like one
quiz question. An empty cell is "not entered", never a 0.
"""
import pytest

import models
from import_task import ValidationError, import_task, validate_task_structure

ABSCHNITTE = [{'id': 'durchfuehrung', 'text': 'Durchführung'},
              {'id': 'auswertung', 'text': 'Auswertung'}]


def topic(abschnitte=ABSCHNITTE, checkpoint_type='artefakt'):
    sub = {'beschreibung': '### 3.7 - Protokoll', 'path': 'wanderweg',
           'checkpoint_type': checkpoint_type, 'kern_standard_tag': 'kern'}
    if abschnitte is not None:
        sub['abschnitte'] = abschnitte
    abnahme = {'beschreibung': '### 3.6 - Abnahme', 'path': 'wanderweg',
               'checkpoint_type': 'abnahme', 'kern_standard_tag': 'kern'}
    return {'task': {'name': '3 - Energetik', 'beschreibung': 'x', 'fach': 'MBI',
                     'stufe': '5', 'subtasks': [abnahme, sub]}}


@pytest.fixture
def fx(db):
    task_id = import_task(topic())
    abnahme, artefakt = models.get_subtasks(task_id)
    klasse = models.create_klasse('11z')
    students = []
    for i, name in enumerate(['Adler', 'Biber']):
        sid = models.create_student(name, 'Kim', f'u{i}', 'pw')
        models.add_student_to_klasse(sid, klasse)
        students.append(sid)
    fid = models.create_fenster(klasse, 'Fenster II', '2026-12-01', '2026-12-20', [task_id], None)
    return {'task': task_id, 'abnahme': dict(abnahme), 'artefakt': dict(artefakt),
            'klasse': klasse, 's': students, 'f': fid}


def save(fx, which, entries, datum='2026-12-10'):
    return models.save_teacher_checkpoint_grades(1, fx[which], fx['klasse'], datum, entries)


def noten(fx):
    import app
    rows, units, _ = app._fenster_noten(models.get_fenster(fx['f']))
    return {r['student']['nachname']: r for r in rows}, units


def test_sections_survive_import_and_export(fx):
    assert models.checkpoint_sections(fx['artefakt']) == ABSCHNITTE
    exported = models.export_task_to_dict(fx['task'])['subtasks'][1]
    assert exported['abschnitte'] == ABSCHNITTE


def test_reimport_without_sections_clears_them(fx):
    data = topic(abschnitte=None)['task']['subtasks']
    models.update_subtasks_from_import(fx['task'], data)
    assert models.checkpoint_sections(models.get_subtask(fx['artefakt']['id'])) == []


@pytest.mark.parametrize('abschnitte, fehler', [
    ([{'text': 'ohne id'}], 'braucht eine id'),
    ([{'id': 'a', 'text': 'x'}, {'id': 'a', 'text': 'y'}], 'doppelt'),
    ([{'id': 'A b', 'text': 'x'}], 'braucht eine id'),
    ([{'id': 'a', 'text': ''}], 'ohne text'),
])
def test_bad_sections_stop_the_import(db, abschnitte, fehler):
    with pytest.raises(ValidationError, match=fehler):
        validate_task_structure(topic(abschnitte))


def test_sections_only_on_teacher_checkpoints(db):
    with pytest.raises(ValidationError, match='abnahme, artefakt oder protokoll'):
        validate_task_structure(topic(checkpoint_type='quiz'))


def test_each_section_is_one_unit_and_counts_for_quality(fx):
    adler, biber = fx['s']
    assert save(fx, 'artefakt', {adler: {'scores': {'durchfuehrung': 3, 'auswertung': 2}}}) == 1
    assert save(fx, 'abnahme', {adler: {'scores': {None: 3}}, biber: {'scores': {None: 0}}}) == 2
    rows, units = noten(fx)
    assert [(u['typ'], u['question_id']) for u in units] == [
        ('abnahme', None), ('artefakt', 'durchfuehrung'), ('artefakt', 'auswertung')]
    assert rows['Adler']['qualitaet'] == pytest.approx(5 * 8 / 3)   # abnahme counts too
    assert rows['Biber']['qualitaet'] == 0


def test_empty_cell_is_a_gap_not_a_zero(fx):
    adler = fx['s'][0]
    save(fx, 'artefakt', {adler: {'scores': {'durchfuehrung': 3}}})
    rows, _ = noten(fx)
    cells = rows['Adler']['cells']
    assert cells[1]['punkte'] == 3
    assert cells[2]['state'] == 'fehlt' and cells[2]['grund'] == 'ohne_wertung'


def test_unchanged_entry_writes_nothing_and_a_correction_wins(fx):
    adler = fx['s'][0]
    entry = {adler: {'scores': {None: 2}, 'notiz': 'sauber'}}
    assert save(fx, 'abnahme', entry) == 1
    assert save(fx, 'abnahme', entry) == 0
    assert save(fx, 'abnahme', {adler: {'scores': {None: 3}, 'notiz': 'sauber'}}) == 1
    rows, _ = noten(fx)
    assert rows['Adler']['cells'][0]['punkte'] == 3
    standing = models.standing_teacher_attempts(fx['abnahme']['id'], [adler])[adler]
    assert standing['teacher_note'] == 'sauber' and standing['reviewed_by'] == 1


def test_note_without_points_is_refused_and_nothing_is_saved(fx):
    adler, biber = fx['s']
    with pytest.raises(ValueError, match='Notiz braucht Punkte'):
        save(fx, 'abnahme', {adler: {'scores': {None: 3}}, biber: {'notiz': 'fehlte'}})
    assert models.standing_teacher_attempts(fx['abnahme']['id'], [adler]) == {}


def test_only_0_2_3(fx):
    with pytest.raises(ValueError, match='0, 2 oder 3'):
        save(fx, 'abnahme', {fx['s'][0]: {'scores': {None: 1}}})


def test_entry_dated_into_a_frozen_window_is_refused(fx):
    models.freeze_fenster(fx['f'], None)
    with pytest.raises(ValueError, match='eingefroren'):
        save(fx, 'abnahme', {fx['s'][0]: {'scores': {None: 3}}}, datum='2026-12-20')
    assert save(fx, 'abnahme', {fx['s'][0]: {'scores': {None: 3}}}, datum='2026-12-21') == 1


def test_entry_after_the_stichtag_does_not_count_in_the_window(fx):
    save(fx, 'abnahme', {fx['s'][0]: {'scores': {None: 3}}}, datum='2026-12-21')
    rows, _ = noten(fx)
    assert rows['Adler']['cells'][0]['grund'] == 'nicht_bearbeitet'


def test_section_added_later_reads_as_frage_neu(fx):
    adler = fx['s'][0]
    save(fx, 'artefakt', {adler: {'scores': {'durchfuehrung': 3, 'auswertung': 3}}})
    data = topic(ABSCHNITTE + [{'id': 'fehler', 'text': 'Fehlerbetrachtung'}])['task']['subtasks']
    models.update_subtasks_from_import(fx['task'], data)
    rows, _ = noten(fx)
    assert rows['Adler']['cells'][3]['grund'] == 'frage_neu'


def test_route_shows_form_and_saves(as_admin, app):
    app.config['WTF_CSRF_ENABLED'] = False
    task_id = import_task(topic())
    artefakt = models.get_subtasks(task_id)[1]
    klasse = models.create_klasse('11z')
    sid = models.create_student('Adler', 'Kim', 'u9', 'pw')
    models.add_student_to_klasse(sid, klasse)
    url = f"/admin/klasse/{klasse}/checkpoint/{artefakt['id']}/eintragen"
    page = as_admin.get(url).get_data(as_text=True)
    assert 'Durchführung' in page and f'p_{sid}_durchfuehrung' in page
    as_admin.post(url, data={'datum': models.now_local()[:10], f'p_{sid}_durchfuehrung': '2',
                             f'p_{sid}_auswertung': '', f'n_{sid}': 'gut'})
    standing = models.standing_teacher_attempts(artefakt['id'], [sid])[sid]
    assert models.attempt_scores_by_id(standing) == {'durchfuehrung': 2, 'auswertung': None}


def test_route_refuses_quiz_checkpoint(as_admin):
    data = topic(abschnitte=None)
    data['task']['subtasks'][1]['checkpoint_type'] = 'quiz'
    data['task']['subtasks'][1]['quiz'] = {'questions': [
        {'text': 'x?', 'options': ['a', 'b'], 'correct': [0]}]}
    task_id = import_task(data)
    quiz = models.get_subtasks(task_id)[1]
    klasse = models.create_klasse('11z')
    assert as_admin.get(f"/admin/klasse/{klasse}/checkpoint/{quiz['id']}/eintragen").status_code == 404


# ---- Protokoll (2026-11-25): own grade, sections required, no kern/standard ----

PROTOKOLL = [{'id': s, 'text': s} for s in
             ('durchfuehrung', 'beobachtungen', 'rechnung', 'deutung',
              'fehlerbetrachtung', 'praktische-durchfuehrung')]


def test_protokoll_needs_sections(db):
    with pytest.raises(ValidationError, match="'protokoll' requires 'abschnitte'"):
        validate_task_structure(topic(abschnitte=None, checkpoint_type='protokoll'))


def test_protokoll_drops_kern_tag_with_a_warning(db):
    warnings = []
    validate_task_structure(topic(PROTOKOLL, 'protokoll'), warnings)
    assert any('ignored' in w for w in warnings)
    task_id = import_task(topic(PROTOKOLL, 'protokoll'))
    assert models.get_subtasks(task_id)[1]['kern_standard_tag'] is None


def test_protokoll_grade_on_the_window_page(db, as_admin):
    task_id = import_task(topic(PROTOKOLL, 'protokoll'))
    protokoll = dict(models.get_subtasks(task_id)[1])
    klasse = models.create_klasse('11z')
    adler = models.create_student('Adler', 'Kim', 'u0', 'pw')
    models.add_student_to_klasse(adler, klasse)
    fid = models.create_fenster(klasse, 'Fenster II', '2026-12-01', '2026-12-20', [task_id], None)
    fx = {'protokoll': protokoll, 'klasse': klasse, 'f': fid}
    save(fx, 'protokoll', {adler: {'scores': {'praktische-durchfuehrung': 3}}})
    rows, _ = noten(fx)
    assert rows['Adler']['protokolle'][0]['offen'] == 5
    assert rows['Adler']['fehlend'] == 1                     # only the unentered 3.6
    scores = {s['id']: 2 for s in PROTOKOLL} | {'durchfuehrung': 3, 'praktische-durchfuehrung': 3}
    save(fx, 'protokoll', {adler: {'scores': scores}})
    rows, _ = noten(fx)
    g = rows['Adler']['protokolle'][0]
    assert (g['be'], g['max'], g['punkte']) == (14, 18, 11)
    page = as_admin.get(f'/admin/bewertungsfenster/{fid}').get_data(as_text=True)
    assert '14 von 18 BE = 11 Punkte' in page and '<th>Arbeitsprozess</th>' not in page
    form = as_admin.get(f"/admin/klasse/{klasse}/checkpoint/{protokoll['id']}/eintragen")
    assert form.status_code == 200 and 'eigene Note' in form.get_data(as_text=True)
