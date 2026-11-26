"""migrate_089: old sittings get per-question points from the answer log.

The case (Chemie 2026-11-24, "bitte fahren"): sittings from before per-question
scores show as `ohne_aufschluesselung` in the Bewertungsfenster, so their questions
are in neither points nor maximum and the grade stays vorläufig for good.
"""
import importlib
import json
import os
import sys

import pytest

import config
import models

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrate'))
mig = importlib.import_module('migrate_089_fragenpunkte_nachrechnen')

QUIZ = json.dumps({'questions': [{'id': f'f{i}', 'type': 'short_answer', 'text': f'Q{i}',
                                  'rubric': 'r'} for i in range(3)]})


@pytest.fixture
def cp(db):
    task = models.create_task('1 - Atome', '', '', 'Chemie', '11', '')
    sub = models.create_subtask(task, '### 1.1', reihenfolge=0, quiz_json=QUIZ,
                                checkpoint_type='quiz', kern_standard_tag='kern')
    student = models.create_student('Adler', 'Kim', 'u1', 'pw')
    return {'task': task, 'sub': sub, 'student': student}


def old_sitting(cp, log, score):
    """log: [(question_index, correct, hints_used_before)] in order. No breakdown stored."""
    tries = {}
    for qi, correct, hints in log:
        tries[qi] = tries.get(qi, 0) + 1
        models.create_checkpoint_answer(cp['student'], cp['sub'], 'uid', qi, tries[qi],
                                        f'a{tries[qi]}', correct, '', 'llm',
                                        hints_used_before=hints)
    return models.create_checkpoint_attempt(
        cp['student'], cp['sub'], cp['task'], 'quiz', 'kern', score=score,
        quiz_snapshot_json=QUIZ, session_uid='uid')


def stored(attempt_id):
    a = models.get_checkpoint_attempt(attempt_id)
    return a['score'], json.loads(a['question_scores_json']), json.loads(a['question_scores_by_id_json'])


def test_fills_breakdown_by_todays_rule(cp):
    aid = old_sitting(cp, [(0, 1, 0), (1, 0, 0), (1, 1, 0), (2, 0, 0)], score=0)
    assert mig.run(config.DATABASE)
    assert stored(aid) == (0, {'0': 3, '1': 2, '2': 0}, {'f0': 3, 'f1': 2, 'f2': 0})
    assert mig.run(config.DATABASE, probelauf=True)      # second run: nothing left


def test_unexplained_mismatch_stops_and_writes_nothing(cp):
    aid = old_sitting(cp, [(0, 1, 0), (1, 1, 0), (2, 0, 0)], score=3)   # log says min 0
    assert not mig.run(config.DATABASE)
    assert models.get_checkpoint_attempt(aid)['question_scores_json'] is None


def test_reported_question_is_none_and_session_follows(cp):
    aid = old_sitting(cp, [(0, 0, 0), (1, 1, 0), (2, 1, 0)], score=0)
    models.create_checkpoint_flag(cp['sub'], 0, 'teacher', status='nachbesserung',
                                  checkpoint_attempt_id=aid)
    assert mig.run(config.DATABASE)
    assert stored(aid)[:2] == (3, {'0': None, '1': 3, '2': 3})
