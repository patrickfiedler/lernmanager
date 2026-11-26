"""Old quiz sittings get their per-question points, rebuilt from the answer log.

Why (Chemie 2026-11-24, "bitte fahren"): sittings from before per-question scores
were stored carry only a session score. The Bewertungsfenster counts per question, so
their questions show as `ohne_aufschluesselung` -- left out of points and maximum,
grade marked vorläufig for good. In production: standing Modul-1 sittings of
2026-08-31 (task_plan.md § Notenrechnung, 5.4).

Rule: the one the student was graded under, `app._checkpoint_question_review` over the
logged answers (no second copy of the 0/2/3 rule). Only questions with answers in the
log and no stored points are filled; stored points are never overwritten.

The session score follows the filled breakdown (min(), `models.consolidate_question_
scores`): `effective_checkpoint_score` already recomputes it from the breakdown once a
question of the checkpoint is excluded, so a stale `score` would show two numbers.
Once every question of the sitting's snapshot has points, the legacy 'vorher' floor
("everything not broken out") has nothing left to stand for and is dropped.

Check, the migration STOPS on a mismatch where nothing explains it: no report on the
sitting and no 'vorher' floor, yet min() differs from the stored score -> the rule
then was not today's, nothing is written. A reported question explains a change: today
it is None (the grade counts it by the report's status), it used to count as 0.

Usage:
    python migrate/migrate_089_fragenpunkte_nachrechnen.py              # config.DATABASE
    python migrate/migrate_089_fragenpunkte_nachrechnen.py --probelauf  # write nothing
    python migrate/migrate_089_fragenpunkte_nachrechnen.py --probelauf path/to/copy.db
"""
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def build_plan(conn):
    """[(attempt_id, filled scores, session score)] and a list of problems."""
    import app
    import models
    conn.row_factory = sqlite3.Row
    attempts = conn.execute('''
        SELECT a.id, a.score, a.question_scores_json, a.quiz_snapshot_json FROM checkpoint_attempt a
        JOIN subtask s ON s.id = a.checkpoint_id
        WHERE a.superseded_at IS NULL AND s.checkpoint_type = 'quiz'
          AND EXISTS (SELECT 1 FROM checkpoint_answer c WHERE c.checkpoint_attempt_id = a.id)
        ORDER BY a.id''').fetchall()
    plan, problems = [], []
    for a in attempts:
        stored = json.loads(a['question_scores_json']) if a['question_scores_json'] else {}
        answers = [dict(r) for r in conn.execute(
            'SELECT * FROM checkpoint_answer WHERE checkpoint_attempt_id = ?', (a['id'],))]
        flagged = {r[0] for r in conn.execute(
            'SELECT question_index FROM checkpoint_flag WHERE checkpoint_attempt_id = ?',
            (a['id'],))}
        review = app._checkpoint_question_review(answers, flagged)
        missing = {str(q['question_index']): q['scored'] for q in review
                   if str(q['question_index']) not in stored}
        if not missing:
            continue
        scores = {**stored, **missing}
        asked = models.quiz_questions(a['quiz_snapshot_json'])
        if 'vorher' in scores and all(str(i) in scores for i in range(len(asked))):
            del scores['vorher']
        session = models.consolidate_question_scores(scores)
        line = f"Sitzung {a['id']}: gespeichert {stored or '-'}, ergänzt {missing}"
        explained = flagged or 'vorher' in stored
        if session != a['score'] and not explained:
            problems.append(f"{line} -> min {session}, gespeichert ist {a['score']}")
            continue
        plan.append((a['id'], scores, session))
        change = (f"Sitzung {a['score']} -> {session} ({'Meldung' if flagged else 'vorher'})"
                  if session != a['score'] else f'Sitzung bleibt {session}')
        print(f'  {line}, {change}')
    return plan, problems


def run(db_path=None, probelauf=False):
    """Returns True on success. Writes nothing when there is any problem."""
    db_path = db_path or config.DATABASE
    config.DATABASE = db_path
    conn = sqlite3.connect(db_path)
    try:
        print(f'{"Probelauf" if probelauf else "Migration"}: {db_path}')
        plan, problems = build_plan(conn)
    finally:
        conn.close()
    if problems:
        print(f'\n{len(problems)} Problem(e), Migration hält an:')
        for p in problems:
            print('  -', p)
        return False
    if probelauf or not plan:
        print(f'{len(plan)} Sitzung(en). {"Probelauf: nichts geschrieben." if probelauf else ""}')
        return True

    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f'Backup created: {backup_path}')
    import models
    for attempt_id, scores, session in plan:
        models.update_checkpoint_attempt_scores(attempt_id, scores, session)
    print(f'{len(plan)} Sitzung(en) nachgerechnet.')
    return True


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--probelauf']
    ok = run(args[0] if args else None, probelauf='--probelauf' in sys.argv)
    sys.exit(0 if ok else 1)
