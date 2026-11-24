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


def _cell(question_id, attempt, scores, excluded, pending):
    """One student x one question. `scores`: the attempt's breakdown by question id,
    or None."""
    if question_id in excluded:
        raw = scores.get(question_id) if scores else None
        return {'state': 'ausgeschlossen', 'points': raw}
    if attempt is None:
        return {'state': 'fehlt', 'points': None}
    if scores is None:
        return {'state': 'unbekannt', 'points': attempt.get('score')}
    if question_id not in scores:
        return {'state': 'fehlt', 'points': None}
    points = scores[question_id]
    if points is None:
        return {'state': 'gemeldet' if question_id in pending else 'ohne_wertung', 'points': None}
    return {'state': 'punkte', 'points': points}


def build_overview(students, checkpoints, attempts, scores_by_attempt, excluded,
                   pending_flags):
    """Arrange everything into rows ready to render.

    students:          [{'id', 'vorname', 'nachname'}]
    checkpoints:       [{'id', 'titel', 'kern', 'questions': [text, ...],
                         'question_ids': [id, ...]}] in page order, today's quiz
    attempts:          {(student_id, checkpoint_id): attempt row} -- standing ones only
    scores_by_attempt: {attempt_id: {question_id: 0|2|3|None}} where a breakdown exists
    excluded:          {checkpoint_id: {question_id: row}} (models.QuestionExclusions)
    pending_flags:     {(student_id, checkpoint_id, question_id)} still waiting on
                       a human (models.PROVISIONAL_FLAG_STATUSES)

    Columns are today's questions; a sitting's score is found by question id, so a
    question deleted or moved since the sitting cannot lend its points to another.

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
            pending = {qid for (sid, cid, qid) in pending_flags
                       if sid == student['id'] and cid == cp['id']}
            for question_id in cp['question_ids']:
                cell = _cell(question_id, attempt, scores, out, pending)
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

    total = sum(len(cp['question_ids']) for cp in checkpoints)
    excluded_count = sum(1 for cp in checkpoints for question_id in cp['question_ids']
                         if question_id in excluded.get(cp['id'], {}))
    return {'rows': rows, 'counted_questions': total - excluded_count,
            'excluded_questions': excluded_count}
