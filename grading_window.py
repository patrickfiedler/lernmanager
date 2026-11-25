"""The grades (0-15) of one Bewertungsfenster, per student: two axes + one Protokoll
grade per required experiment.

Pure functions, no Flask and no database: the numbers a
grade is read off must be testable without a browser. app._fenster_noten loads the
rows, this module only decides what each unit is worth and adds it up.

Rules: Chemie `docs/32-bewertungsregeln.md` § 3, § 3a, § 6 and § 9b; plan in
`task_plan.md` § Chemies Notenrechnung, Phase 2 + 3b. Since 2026-11-25 the
Arbeitsprozess axis is merged into quality and a Protokoll is its own grade
(decision 2026-11-25-protokoll-eigene-note-arbeitsprozess-verschmolzen).

Unit = what one 0/2/3 belongs to:
    quiz checkpoint             one unit per question of today's quiz
    abnahme/artefakt/protokoll  one unit per teacher-graded section, else one unit
                                for the whole thing

State of one student x one unit:
    punkte      0, 2 or 3 -- counts
    fehlt       no score: counts as 0. `grund` says why (nicht_bearbeitet,
                frage_neu, llm_kontingent, abgelehnt, nachbesserung, frage_kaputt, ...).
                A reason is a report field only, never an exclusion (Chemie 2026-09-01)
    vorlaeufig  open report, or a sitting without per-question scores: in neither
                points nor maximum, and the whole result is marked provisional
                (§ 9b: optimistic until the Stichtag)

Excluded for everyone (checkpoint_question_exclusion) and questions deleted from the
quiz are not units at all.
"""

import json
from functools import lru_cache
from pathlib import Path

MAX_POINTS = 3
SOLVED = 2          # a question counts as solved from 2 points (§ 3)

# Reports that still wait on a teacher. 'abgelehnt' and 'nachbesserung' do not: the
# teacher has ruled and the student owes the question, so it counts 0 until redone.
OPEN_FLAG = 'offen'

# Why a unit has no score, as the admin pages say it (window page + overview)
REASONS = {
    'nicht_bearbeitet': 'nicht bearbeitet', 'llm_kontingent': 'nicht gestellt (KI-Kontingent)',
    'frage_neu': 'Frage nach der Sitzung neu, nachholen',
    'abgelehnt': 'Meldung abgelehnt, nachholen', 'nachbesserung': 'zur Nachbesserung zurück',
    'frage_kaputt': 'Frage kaputt', 'kontext_falsch': 'falscher Platz',
    'design_fehlerhaft': 'Aufgabe bereitet nicht vor', 'ohne_wertung': 'ohne Wertung',
    'gemeldet': 'gemeldet, wartet auf Entscheidung',
    'ohne_aufschluesselung': 'alte Sitzung ohne Punkte je Frage',
}

# Official Punktetabelle Oberstufe, one lookup per total BE (copy of
# docs/shared/lernmanager/chemie-punktetabelle-oberstufe.json -- the symlink is not
# on the server). A table, not a formula: the official one has gaps and repeated
# thresholds no percentage rule reproduces.
POINTS_TABLE = Path(__file__).with_name('punktetabelle_oberstufe.json')


@lru_cache(maxsize=1)
def _points_table():
    return json.loads(POINTS_TABLE.read_text(encoding='utf-8'))['tabellen']


def notenpunkte(be, max_be):
    """Notenpunkte for `be` of `max_be` BE; None when the table has no such total."""
    return _points_table().get(str(max_be), {}).get(str(be))


def expected_units(checkpoints, excluded):
    """The window's denominator: one dict per unit, in page order.

    checkpoints: [{'id', 'checkpoint_type', 'kern_standard_tag', 'question_ids'}],
                 question_ids = ids of today's quiz ([] = no quiz)
    excluded:    {checkpoint_id: QuestionExclusions} (anything with `in`)

    Returns (units, excluded_count). Unit: {'checkpoint_id', 'question_id' (None =
    whole checkpoint), 'typ', 'niveau'}.
    """
    units, out = [], 0
    for cp in checkpoints:
        gone = excluded.get(cp['id'], ())
        question_ids = cp.get('question_ids') or [None]
        for question_id in question_ids:
            if question_id is not None and question_id in gone:
                out += 1
                continue
            units.append({'checkpoint_id': cp['id'], 'question_id': question_id,
                          'typ': cp['checkpoint_type'], 'niveau': cp.get('kern_standard_tag')})
    return units, out


def _snapshot_ids(attempt):
    """IDs of the questions the sitting actually showed, None if unknown."""
    raw = attempt.get('quiz_snapshot_json')
    if not raw:
        return None
    quiz = json.loads(raw)
    questions = quiz if isinstance(quiz, list) else quiz.get('questions')
    if questions is None:
        return None
    return {q.get('id') for q in questions}


def unit_cell(unit, attempt, scores, running, flags):
    """One student x one unit -> {'state', 'punkte', 'grund'}.

    attempt: the standing checkpoint_attempt row, or None
    scores:  that attempt's {question_id: 0|2|3|None}, None = no breakdown stored
    running: {question_id: 2|3} solved in a sitting not finished yet (§ 9b: counts)
    flags:   {question_id: status of the newest report by this student}
    """
    qid = unit['question_id']
    if attempt is None:
        if qid in running:
            return {'state': 'punkte', 'punkte': running[qid], 'grund': 'laufend'}
        if flags.get(qid) == OPEN_FLAG:
            return {'state': 'vorlaeufig', 'punkte': None, 'grund': 'gemeldet'}
        return {'state': 'fehlt', 'punkte': None, 'grund': 'nicht_bearbeitet'}
    if qid is None:                      # whole checkpoint scored as one
        return {'state': 'punkte', 'punkte': attempt['score'], 'grund': None}
    if scores is None:
        return {'state': 'vorlaeufig', 'punkte': None, 'grund': 'ohne_aufschluesselung'}
    if qid not in scores:
        # Not in the sitting's own snapshot = question came in after the student
        # sat it (ID rule: new question, open for all, 0 until done). In it but
        # unscored = the grader gave nothing back.
        asked = _snapshot_ids(attempt)
        grund = 'frage_neu' if asked is not None and qid not in asked else 'llm_kontingent'
        return {'state': 'fehlt', 'punkte': None, 'grund': grund}
    if scores[qid] is not None:
        return {'state': 'punkte', 'punkte': scores[qid], 'grund': None}
    status = flags.get(qid)
    if status == OPEN_FLAG:
        return {'state': 'vorlaeufig', 'punkte': None, 'grund': 'gemeldet'}
    return {'state': 'fehlt', 'punkte': None, 'grund': status or 'ohne_wertung'}


def _mean_x5(cells):
    counted = [c for c in cells if c['state'] != 'vorlaeufig']
    if not counted:
        return None
    return 5 * sum(c['punkte'] or 0 for c in counted) / len(counted)


def _share_solved(cells):
    """(solved, counted): vorläufig units are in neither."""
    counted = [c for c in cells if c['state'] != 'vorlaeufig']
    return sum(1 for c in counted if (c['punkte'] or 0) >= SOLVED), len(counted)


def axes(units, cells):
    """The two axes for one student. units and cells: same length, same order.

    qualitaet      "Qualität des Arbeitsprozesses": mean of quiz + artefakt + abnahme
                   units x 5; capped at 10 while the window offers a standard quiz
                   question and none is solved (§ 6). Artefakt and abnahme never
                   lift the cap (§ 9b)
    abdeckung      10 x share of kern solved + 5 x share of standard solved, capped
                   at 10 while a kern question is unsolved (§ 3). Quiz only
    punkte / max   raw sum and maximum (3 per unit that is not vorläufig), what the
                   checkpoint overview reads at a glance
    fehlend / offen units without a score (count 0) / reported and undecided
    Protokoll units are in none of these (own grade, see protokoll_noten).
    """
    pairs = [(u, c) for u, c in zip(units, cells) if u['typ'] != 'protokoll']
    quiz = [(u, c) for u, c in pairs if u['typ'] == 'quiz']
    kern = [c for u, c in quiz if u['niveau'] != 'standard']
    standard = [c for u, c in quiz if u['niveau'] == 'standard']

    qualitaet = _mean_x5([c for u, c in pairs if u['typ'] in ('quiz', 'artefakt', 'abnahme')])
    standard_solved, _ = _share_solved(standard)
    if qualitaet is not None and standard and not standard_solved:
        qualitaet = min(qualitaet, 10)

    k_solved, k_total = _share_solved(kern)
    s_solved, s_total = _share_solved(standard)
    abdeckung = None
    if k_total or s_total:
        # Empty share = 0 points (window without standard: abdeckung tops at 10).
        # Open question to Chemie, see task_plan.md § Phase 2.
        abdeckung = (10 * k_solved / k_total if k_total else 0) \
            + (5 * s_solved / s_total if s_total else 0)
        if k_solved < k_total:
            abdeckung = min(abdeckung, 10)

    return {'qualitaet': qualitaet,
            'abdeckung': abdeckung,
            'vorlaeufig': any(c['state'] == 'vorlaeufig' for _, c in pairs),
            'fehlend': sum(1 for _, c in pairs if c['state'] == 'fehlt'),
            'punkte': sum(c['punkte'] or 0 for _, c in pairs if c['state'] == 'punkte'),
            'max': MAX_POINTS * sum(1 for _, c in pairs if c['state'] != 'vorlaeufig'),
            'offen': sum(1 for _, c in pairs if c['grund'] == 'gemeldet'),
            'offene_kern': [u for u, c in quiz if u['niveau'] != 'standard' and _open(c)]}


def protokoll_noten(units, cells):
    """One grade per Protokoll checkpoint (§ 3a), in page order.

    BE = sum of the sections' 0/2/3, maximum 3 per section. An empty section is
    "not entered yet", never 0 (the Abnahme section is usually entered weeks before
    the rest), so Notenpunkte come only once every section has a score; until then
    `offen` counts the empty ones. Without a table entry for the total: BE only.
    """
    grades = {}
    for u, c in zip(units, cells):
        if u['typ'] != 'protokoll':
            continue
        g = grades.setdefault(u['checkpoint_id'], {
            'checkpoint_id': u['checkpoint_id'], 'titel': u.get('titel'),
            'be': 0, 'max': 0, 'offen': 0, 'punkte': None})
        g['max'] += MAX_POINTS
        if c['state'] == 'punkte':
            g['be'] += c['punkte']
        else:
            g['offen'] += 1
    for g in grades.values():
        if not g['offen']:
            g['punkte'] = notenpunkte(g['be'], g['max'])
    return list(grades.values())


def _open(cell):
    """Unsolved and up to the student (a reported question waits on the teacher)."""
    return cell['state'] == 'fehlt' or (cell['state'] == 'punkte' and cell['punkte'] < SOLVED)


def build_noten(students, units, per_student):
    """Rows ready to render.

    per_student: {student_id: {'attempts': {cid: row}, 'scores': {cid: {qid: s}|None},
                               'running': {cid: {qid: s}}, 'flags': {cid: {qid: status}}}}
    Returns [{'student', 'cells', **axes}] in the order of `students`.
    """
    rows = []
    for student in students:
        data = per_student.get(student['id'], {})
        cells = []
        for unit in units:
            cid = unit['checkpoint_id']
            attempt = data.get('attempts', {}).get(cid)
            cell = unit_cell(unit, attempt, data.get('scores', {}).get(cid),
                             data.get('running', {}).get(cid, {}),
                             data.get('flags', {}).get(cid, {}))
            cell['attempt_id'] = attempt['id'] if attempt else None   # for links
            cells.append(cell)
        rows.append({'student': student, 'cells': cells, **axes(units, cells),
                     'protokolle': protokoll_noten(units, cells)})
    return rows
