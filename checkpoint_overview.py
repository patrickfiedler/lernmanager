"""Points per student and question across the checkpoints of one Thema.

Pure functions, no Flask and no database: the numbers a grade is read off must be
testable without a browser. The route (app.admin_checkpoint_uebersicht) loads the
rows, this module only arranges and adds them up.

What a cell can be:

    punkte         0, 2 or 3 -- counts
    fehlt          the student has no score for it: checkpoint never sat, or the
                   question was not part of the sitting (LLM budget spent). Counts
                   as 0 of 3.
    gemeldet       reported, no verdict yet (or a redo is owed). No points and not in
                   the maximum until that is settled.
    ohne_wertung   left out for THIS student (their report was confirmed)
    ausgeschlossen left out for EVERYONE (checkpoint_question_exclusion). The points
                   the student had are shown, struck through, and count nowhere.
    unbekannt      sitting from before per-question scores were stored; only its
                   session score is known. Not in the sums.
"""
MAX_POINTS = 3


def _cell(index, attempt, scores, excluded, pending):
    """One student x one question. `scores`: the attempt's stored breakdown or None."""
    if index in excluded:
        raw = scores.get(str(index)) if scores else None
        return {'state': 'ausgeschlossen', 'points': raw}
    if attempt is None:
        return {'state': 'fehlt', 'points': None}
    if scores is None:
        return {'state': 'unbekannt', 'points': attempt.get('score')}
    if str(index) not in scores:
        return {'state': 'fehlt', 'points': None}
    points = scores[str(index)]
    if points is None:
        return {'state': 'gemeldet' if index in pending else 'ohne_wertung', 'points': None}
    return {'state': 'punkte', 'points': points}


def build_overview(students, checkpoints, attempts, scores_by_attempt, excluded,
                   pending_flags):
    """Arrange everything into rows ready to render.

    students:          [{'id', 'vorname', 'nachname'}]
    checkpoints:       [{'id', 'titel', 'kern', 'questions': [text, ...]}] in page order
    attempts:          {(student_id, checkpoint_id): attempt row} -- standing ones only
    scores_by_attempt: {attempt_id: {"<index>": 0|2|3|None}} where a breakdown exists
    excluded:          {checkpoint_id: {question_index: row}}
    pending_flags:     {(student_id, checkpoint_id, question_index)} still waiting on
                       a human (models.PROVISIONAL_FLAG_STATUSES)

    Returns {'rows': [...], 'counted_questions': n, 'excluded_questions': n}. Each
    row: {'student', 'cells' (flat, in column order), 'points', 'max', 'fehlend',
    'offen'}. `max` is 3 x the questions that count for this student right now.
    """
    rows = []
    for student in students:
        cells, points, counted, fehlend, offen = [], 0, 0, 0, 0
        for cp in checkpoints:
            attempt = attempts.get((student['id'], cp['id']))
            scores = scores_by_attempt.get(attempt['id']) if attempt else None
            out = excluded.get(cp['id'], {})
            pending = {idx for (sid, cid, idx) in pending_flags
                       if sid == student['id'] and cid == cp['id']}
            for index in range(len(cp['questions'])):
                cell = _cell(index, attempt, scores, out, pending)
                cells.append(cell)
                if cell['state'] == 'punkte':
                    points += cell['points']
                    counted += 1
                elif cell['state'] == 'fehlt':
                    fehlend += 1
                    counted += 1
                elif cell['state'] == 'gemeldet':
                    offen += 1
        rows.append({'student': student, 'cells': cells, 'points': points,
                     'max': counted * MAX_POINTS, 'fehlend': fehlend, 'offen': offen})

    total = sum(len(cp['questions']) for cp in checkpoints)
    excluded_count = sum(1 for cp in checkpoints
                         for index in range(len(cp['questions']))
                         if index in excluded.get(cp['id'], {}))
    return {'rows': rows, 'counted_questions': total - excluded_count,
            'excluded_questions': excluded_count}
