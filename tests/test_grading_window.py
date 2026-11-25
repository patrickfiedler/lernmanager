"""Rechenwerk of a Bewertungsfenster (task_plan.md § Notenrechnung, Phase 2).

Formulas: Chemie docs/32-bewertungsregeln.md § 3, § 6, § 9b. The worked examples
from that document are the first tests here.
"""
import json

import pytest

import grading_window as gw
import models


def unit(typ='quiz', niveau='kern', cid=1, qid='f1'):
    return {'checkpoint_id': cid, 'question_id': qid, 'typ': typ, 'niveau': niveau}


def pts(p):
    return {'state': 'punkte', 'punkte': p, 'grund': None}


FEHLT = {'state': 'fehlt', 'punkte': None, 'grund': 'nicht_bearbeitet'}
OFFEN = {'state': 'vorlaeufig', 'punkte': None, 'grund': 'gemeldet'}


# ---- the three axes, pure ----

def test_docs32_example_quality_capped_without_solved_standard():
    """§ 6: 24 kern on 3, 6 standard untouched -> 72/30*5 = 12, capped at 10."""
    units = [unit()] * 24 + [unit(niveau='standard')] * 6
    a = gw.axes(units, [pts(3)] * 24 + [FEHLT] * 6)
    assert a['qualitaet'] == 10
    assert a['abdeckung'] == 10          # kern full, no standard solved


def test_one_solved_standard_lifts_both_caps():
    units = [unit()] * 24 + [unit(niveau='standard')] * 6
    a = gw.axes(units, [pts(3)] * 24 + [pts(2)] + [FEHLT] * 5)
    assert a['qualitaet'] == pytest.approx(5 * 74 / 30)
    assert a['abdeckung'] == pytest.approx(10 + 5 / 6)


def test_docs32_example_one_open_kern_caps_coverage():
    """§ 9.1: 24 kern, one open -> 9.6 kern points; standard does not count yet."""
    units = [unit()] * 24 + [unit(niveau='standard')] * 2
    a = gw.axes(units, [pts(3)] * 23 + [FEHLT] + [pts(3)] * 2)
    assert a['abdeckung'] == 10          # 9.58 + 5, capped while kern is open
    assert len(a['offene_kern']) == 1


def test_window_without_standard_has_no_quality_cap():
    a = gw.axes([unit()] * 4, [pts(3)] * 4)
    assert a['qualitaet'] == 15
    assert a['abdeckung'] == 10          # empty standard share = 0 (open question)


def test_open_report_is_in_neither_points_nor_maximum():
    a = gw.axes([unit()] * 3, [pts(3), pts(3), OFFEN])
    assert a['qualitaet'] == 15 and a['vorlaeufig']
    assert a['offene_kern'] == []        # waits on the teacher, not on the student


def test_abnahme_is_its_own_axis_without_cap():
    units = [unit()] * 2 + [unit(niveau='standard')] + [unit('abnahme', qid=None, cid=2)]
    a = gw.axes(units, [pts(3), pts(3), FEHLT, pts(3)])
    assert a['arbeitsprozess'] == 15
    assert a['qualitaet'] == 10


def test_artefakt_counts_for_quality_but_not_coverage_or_cap():
    units = [unit(), unit(niveau='standard'), unit('artefakt', niveau='standard', cid=3)]
    a = gw.axes(units, [pts(3), FEHLT, pts(3)])
    assert a['qualitaet'] == 10          # artefakt section does not lift the cap (§ 9b)
    assert a['abdeckung'] == 10          # kern 1/1, standard 0/1
    assert a['arbeitsprozess'] is None


# ---- cells ----

def test_cell_reasons():
    u = unit(qid='f2')
    attempt = {'score': 2}
    assert gw.unit_cell(u, None, None, {}, {})['grund'] == 'nicht_bearbeitet'
    assert gw.unit_cell(u, None, None, {'f2': 3}, {}) == {'state': 'punkte', 'punkte': 3,
                                                          'grund': 'laufend'}
    assert gw.unit_cell(u, attempt, {'f1': 3}, {}, {})['grund'] == 'llm_kontingent'
    assert gw.unit_cell(u, attempt, None, {}, {})['state'] == 'vorlaeufig'
    assert gw.unit_cell(u, attempt, {'f2': None}, {}, {'f2': 'offen'})['state'] == 'vorlaeufig'
    cell = gw.unit_cell(u, attempt, {'f2': None}, {}, {'f2': 'frage_kaputt'})
    assert cell == {'state': 'fehlt', 'punkte': None, 'grund': 'frage_kaputt'}
    whole = unit('abnahme', qid=None)
    assert gw.unit_cell(whole, attempt, None, {}, {}) == pts(2)


def test_excluded_and_removed_questions_are_no_units():
    excluded = {1: models.QuestionExclusions({'f2': {}}, current_ids=['f1', 'f2'])}
    units, out = gw.expected_units(
        [{'id': 1, 'checkpoint_type': 'quiz', 'kern_standard_tag': 'kern',
          'question_ids': ['f1', 'f2']},
         {'id': 2, 'checkpoint_type': 'abnahme', 'kern_standard_tag': 'kern',
          'question_ids': []}], excluded)
    assert [(u['checkpoint_id'], u['question_id']) for u in units] == [(1, 'f1'), (2, None)]
    assert out == 1


# ---- loader + app glue against a real database ----

def quiz(n):
    return json.dumps({'questions': [{'type': 'short_answer', 'text': f'Q{i}', 'rubric': 'r'}
                                     for i in range(n)]})


@pytest.fixture
def fenster(db):
    klasse = models.create_klasse('11z')
    task = models.create_task('1 - Atome', '', '', 'Chemie', '11', '')
    kern = models.create_subtask(task, '### 1.1 - Kern', reihenfolge=0, quiz_json=quiz(2),
                                 checkpoint_type='quiz', kern_standard_tag='kern')
    std = models.create_subtask(task, '### 1.2 - Standard', reihenfolge=1, quiz_json=quiz(1),
                                checkpoint_type='quiz', kern_standard_tag='standard')
    students = []
    for i, name in enumerate(['Adler', 'Biber']):
        sid = models.create_student(name, 'Kim', f'u{i}', 'pw')
        models.add_student_to_klasse(sid, klasse)
        students.append(sid)
    fid = models.create_fenster(klasse, 'Fenster II', '2026-11-01', '2026-11-20', [task], None)
    return {'f': fid, 'task': task, 'kern': kern, 'std': std, 's': students}


def sit(fx, student, cp, scores, timestamp):
    return models.create_checkpoint_attempt(
        student, cp, fx['task'], 'quiz', 'kern' if cp == fx['kern'] else 'standard',
        score=min(v for v in scores.values() if v is not None), timestamp=timestamp,
        quiz_snapshot_json=models.get_subtask(cp)['quiz_json'],
        question_scores_json=json.dumps(scores))


def noten(fx):
    import app
    rows, units, _ = app._fenster_noten(models.get_fenster(fx['f']))
    return {r['student']['nachname']: r for r in rows}, units


def test_window_grades_from_database(fenster):
    fx = fenster
    sit(fx, fx['s'][0], fx['kern'], {'0': 3, '1': 2}, '2026-11-10 09:00:00')
    sit(fx, fx['s'][0], fx['std'], {'0': 3}, '2026-11-10 09:10:00')
    rows, units = noten(fx)
    assert len(units) == 3
    adler, biber = rows['Adler'], rows['Biber']
    assert adler['qualitaet'] == pytest.approx(5 * 8 / 3)
    assert adler['abdeckung'] == 15
    assert biber['qualitaet'] == 0 and biber['fehlend'] == 3


def test_only_what_stood_at_the_stichtag_counts(fenster):
    fx = fenster
    first = sit(fx, fx['s'][0], fx['kern'], {'0': 3, '1': 3}, '2026-11-10 09:00:00')
    models.supersede_checkpoint_attempts([first])
    with models.db_session() as conn:     # reset + retake after the Stichtag
        conn.execute("UPDATE checkpoint_attempt SET superseded_at = '2026-11-22 08:00:00'")
    sit(fx, fx['s'][0], fx['kern'], {'0': 0, '1': 0}, '2026-11-22 09:00:00')
    rows, _ = noten(fx)
    assert rows['Adler']['cells'][0] == pts(3)


def test_running_sitting_counts_its_solved_questions(fenster):
    fx = fenster
    question = models.quiz_questions(models.get_subtask(fx['kern'])['quiz_json'])[0]
    models.create_checkpoint_answer(fx['s'][1], fx['kern'], 'uid-1', 0, None, 'x', True,
                                    '', 'exact', question=question)
    rows, _ = noten(fx)
    assert rows['Biber']['cells'][0]['grund'] == 'nicht_bearbeitet'   # after the Stichtag
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET timestamp = '2026-11-15 09:00:00'")
    rows, _ = noten(fx)
    assert rows['Biber']['cells'][0] == {'state': 'punkte', 'punkte': 3, 'grund': 'laufend'}
    assert rows['Biber']['cells'][1]['grund'] == 'nicht_bearbeitet'
