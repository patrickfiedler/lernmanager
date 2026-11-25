"""The three grade axes (0-15) of one Bewertungsfenster, per student.

Pure functions, no Flask and no database, same as checkpoint_overview: the numbers a
grade is read off must be testable without a browser. app._fenster_noten loads the
rows, this module only decides what each unit is worth and adds it up.

Rules: Chemie `docs/32-bewertungsregeln.md` § 3, § 6 and § 9b; plan in
`task_plan.md` § Chemies Notenrechnung, Phase 2.

Unit = what one 0/2/3 belongs to:
    quiz checkpoint             one unit per question of today's quiz
    abnahme / artefakt          one unit per question if the checkpoint has a quiz
                                (sections, Phase 3), else one unit for the whole thing

State of one student x one unit:
    punkte      0, 2 or 3 -- counts
    fehlt       no score: counts as 0. `grund` says why (nicht_bearbeitet,
                llm_kontingent, abgelehnt, nachbesserung, frage_kaputt, ...).
                A reason is a report field only, never an exclusion (Chemie 2026-09-01)
    vorlaeufig  open report, or a sitting without per-question scores: in neither
                points nor maximum, and the whole result is marked provisional
                (§ 9b: optimistic until the Stichtag)

Excluded for everyone (checkpoint_question_exclusion) and questions deleted from the
quiz are not units at all.
"""
MAX_POINTS = 3
SOLVED = 2          # a question counts as solved from 2 points (§ 3)

# Reports that still wait on a teacher. 'abgelehnt' and 'nachbesserung' do not: the
# teacher has ruled and the student owes the question, so it counts 0 until redone.
OPEN_FLAG = 'offen'


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
        return {'state': 'fehlt', 'punkte': None, 'grund': 'llm_kontingent'}
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
    """The three axes for one student. units and cells: same length, same order.

    qualitaet      mean of quiz + artefakt units x 5; capped at 10 while the window
                   offers a standard quiz question and none is solved (§ 6). An
                   artefakt section never lifts the cap (§ 9b)
    arbeitsprozess mean of abnahme units x 5, no cap; None without any abnahme
    abdeckung      10 x share of kern solved + 5 x share of standard solved, capped
                   at 10 while a kern question is unsolved (§ 3). Quiz only:
                   artefakt carries no kern/standard (§ 3), abnahme is its own axis
    """
    pairs = list(zip(units, cells))
    quiz = [(u, c) for u, c in pairs if u['typ'] == 'quiz']
    kern = [c for u, c in quiz if u['niveau'] != 'standard']
    standard = [c for u, c in quiz if u['niveau'] == 'standard']

    qualitaet = _mean_x5([c for u, c in pairs if u['typ'] in ('quiz', 'artefakt')])
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
            'arbeitsprozess': _mean_x5([c for u, c in pairs if u['typ'] == 'abnahme']),
            'abdeckung': abdeckung,
            'vorlaeufig': any(c['state'] == 'vorlaeufig' for c in cells),
            'fehlend': sum(1 for c in cells if c['state'] == 'fehlt'),
            'offene_kern': [u for u, c in quiz if u['niveau'] != 'standard' and _open(c)]}


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
            cells.append(unit_cell(unit, attempt,
                                   data.get('scores', {}).get(cid),
                                   data.get('running', {}).get(cid, {}),
                                   data.get('flags', {}).get(cid, {})))
        rows.append({'student': student, 'cells': cells, **axes(units, cells)})
    return rows
