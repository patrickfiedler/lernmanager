"""The "Fragen" tab: the review page's sessions regrouped by question.

Patrick, 2026-09-04. The page groups by session because grading is per student, but
"is this question broken?" is a claim about the question across the class, and
answering it meant opening every session and holding the pattern in your head.

Three detectors, kept separate on purpose (checkpoint_questions module docstring):
failure/report/give-up rate, failure CLUSTERING, and grader confidence. The second is
the one that says students went wrong *the same way*. The third only reports how often
the grader hesitated -- measured 2026-09-04, it does NOT predict which questions
students report as broken, so nothing here treats it as a quality signal.
"""
import json
import re

import checkpoint_questions as cq
import models


def _session(attempt_id, student_id, questions, checkpoint_id=7, superseded=None,
             timestamp='2026-09-02 09:00:00'):
    """One entry in app._build_checkpoint_sessions' shape, trimmed to what the
    question view reads."""
    return {
        'attempt': {
            'id': attempt_id, 'student_id': student_id, 'checkpoint_id': checkpoint_id,
            'student_name': f'Schueler {student_id}', 'task_name': 'Atommodelle',
            'subtask_name': 'Checkpoint 1.4', 'timestamp': timestamp,
            'superseded_at': superseded,
        },
        'questions': questions,
    }


def _question(index=0, text='Warum leuchtet Natrium gelb?', scored=3, answers=(),
              flags=(), qtype='short_answer'):
    return {
        'question_index': index, 'question_text': text, 'question_type': qtype,
        'rubric': None, 'correct_display': None, 'scored': scored,
        'flags': list(flags), 'answers': list(answers),
    }


def _answer(correct=True, feedback=None, gave_up=False, confidence=None):
    return {'correct': correct, 'feedback': feedback, 'gave_up': gave_up,
            'judgment_confidence': confidence}


# --- the three counts -------------------------------------------------------

def test_reported_is_counted_apart_from_failed():
    """`scored is None` means a student reported the question and no verdict exists
    yet. Counting it as a failure would be a claim nobody has made; counting it as a
    pass would hide the strongest signal there is."""
    rows = cq.build_question_view([
        _session(1, 1, [_question(scored=None)]),
        _session(2, 2, [_question(scored=0)]),
        _session(3, 3, [_question(scored=3)]),
    ])
    row = rows[0]
    assert row['reported_count'] == 1
    assert row['failed_count'] == 1
    assert row['student_count'] == 3
    assert row['concern_count'] == 2


def test_reports_lift_a_question_up_the_list():
    """Regression on the first ordering: a question 8 of 12 students had reported sat
    17th because it was ranked on failures alone, and reports zero the failure count
    by design. Ranking on 'went wrong in any way' is what surfaces it."""
    reported = [_session(i, i, [_question(index=0, scored=None)]) for i in range(1, 9)]
    failed_a_bit = [_session(10 + i, 10 + i, [_question(index=1, text='Andere Frage',
                                                        scored=0 if i < 2 else 3)])
                    for i in range(8)]
    rows = cq.build_question_view(reported + failed_a_bit)
    assert rows[0]['question_index'] == 0
    assert rows[0]['reported_count'] == 8


def test_superseded_sessions_are_not_evidence():
    """A reset session is history -- it must not keep a repaired question looking
    broken."""
    rows = cq.build_question_view([
        _session(1, 1, [_question(scored=0)], superseded='2026-09-03 10:00:00'),
        _session(2, 2, [_question(scored=3)]),
    ])
    assert rows[0]['student_count'] == 1
    assert rows[0]['failed_count'] == 0


# --- clustering -------------------------------------------------------------

def test_students_failing_the_same_way_cluster():
    same = 'Die Antwort nennt die Kathode als Pluspol, richtig ist der Minuspol.'
    rows = cq.build_question_view([
        _session(i, i, [_question(scored=0, answers=[_answer(False, same)])])
        for i in range(1, 5)
    ])
    cluster = rows[0]['cluster']
    assert cluster is not None
    assert cluster['size'] == 4
    assert 'kathode' in cluster['terms']


def test_unrelated_failures_do_not_cluster():
    """The signal has to be able to say no, or it says nothing."""
    rows = cq.build_question_view([
        _session(1, 1, [_question(scored=0, answers=[
            _answer(False, 'Die Reaktionsgleichung ist nicht ausgeglichen.')])]),
        _session(2, 2, [_question(scored=0, answers=[
            _answer(False, 'Der Satz bricht mittendrin ab.')])]),
        _session(3, 3, [_question(scored=0, answers=[
            _answer(False, 'Hier fehlt jede Begründung zum Energieniveau.')])]),
    ])
    assert rows[0]['cluster'] is None


def test_give_ups_never_feed_the_cluster():
    """On a give-up the stored feedback is the model solution, identical for every
    student by construction. Including those makes every question cluster at 1.00 --
    a maximally strong signal exactly where it means nothing. Found while building
    this: it dominated the first exploration of the production exports."""
    solution = 'Rückstromphase = galvanisch, Elektrolysephase = elektrolytisch.'
    rows = cq.build_question_view([
        _session(i, i, [_question(scored=0,
                                  answers=[_answer(None, solution, gave_up=True)])])
        for i in range(1, 5)
    ])
    assert rows[0]['cluster'] is None
    assert rows[0]['gave_up_count'] == 4


def test_cluster_denominator_is_the_population_it_was_drawn_from():
    """Regression: the denominator used to be failed_count, which produced impossible
    lines like "6 von 4 scheitern ähnlich" -- a reported question carries wrong
    answers but, by design, no failure."""
    same = 'Die Kathode ist hier falsch zugeordnet, sie ist der Minuspol.'
    rows = cq.build_question_view([
        _session(i, i, [_question(scored=None, answers=[_answer(False, same)])])
        for i in range(1, 5)
    ])
    row = rows[0]
    assert row['failed_count'] == 0            # all reported, none scored
    assert row['clusterable_count'] == 4
    assert row['cluster']['size'] <= row['clusterable_count']


def test_only_the_last_wrong_answer_per_student_counts():
    """One stubborn student retrying eight times must not look like eight students
    agreeing."""
    rows = cq.build_question_view([
        _session(1, 1, [_question(scored=0, answers=[
            _answer(False, 'Die Kathode ist der Pluspol, das stimmt nicht.'),
            _answer(False, 'Die Kathode ist der Pluspol, das stimmt nicht.'),
            _answer(False, 'Die Kathode ist der Pluspol, das stimmt nicht.'),
        ])]),
    ])
    assert rows[0]['clusterable_count'] == 1
    assert rows[0]['cluster'] is None          # one student is not a pattern


# --- wording drift ----------------------------------------------------------

def test_two_wordings_at_one_index_are_reported_as_drift():
    """6 of 24 (checkpoint, index) slots in the 2026-08/09 production data carry more
    than one wording. A batch keyed on the index alone would act on students who
    answered a different question."""
    rows = cq.build_question_view([
        _session(1, 1, [_question(text='Alte Fassung')], timestamp='2026-08-26 09:00:00'),
        _session(2, 2, [_question(text='Neue Fassung')], timestamp='2026-09-02 09:00:00'),
        _session(3, 3, [_question(text='Neue Fassung')], timestamp='2026-09-02 09:10:00'),
    ])
    row = rows[0]
    assert row['has_drift'] is True
    assert len(row['variants']) == 2
    # The commonest wording is the reference; the rest are held apart, never merged.
    assert row['wording'] == 'Neue Fassung'
    assert sorted(row['attempt_ids']) == [2, 3]
    assert row['divergent_attempt_ids'] == [1]


def test_a_single_wording_is_not_drift():
    rows = cq.build_question_view([
        _session(1, 1, [_question(text='Eine Fassung')]),
        _session(2, 2, [_question(text='Eine Fassung')]),
    ])
    assert rows[0]['has_drift'] is False
    assert rows[0]['divergent_attempt_ids'] == []


# --- confidence -------------------------------------------------------------

def test_unsure_judgments_are_counted_not_averaged():
    """The average hides the structure that exists: 1.3 F1 in the production exports
    carries 7 unsure judgments out of 38 and still averages 0.92, which reads as
    mild. The count is what the badge shows."""
    row = cq.build_question_view([
        _session(1, 1, [_question(scored=0, answers=[_answer(False, 'x', confidence=0.6)])]),
        _session(2, 2, [_question(scored=0, answers=[_answer(False, 'y', confidence=0.7)])]),
        _session(3, 3, [_question(scored=3, answers=[_answer(True, confidence=0.99)])]),
    ])[0]
    assert row['unsure_count'] == 2
    assert row['confidence_min'] == 0.6
    assert row['confidence_n'] == 3

    confident = cq.build_question_view([
        _session(1, 1, [_question(answers=[_answer(True, confidence=0.999)])]),
    ])[0]
    assert confident['unsure_count'] == 0


def test_missing_confidence_is_not_zero():
    """NULL means 'no LLM graded this', which must never read as 'the model was
    certain it was wrong' -- the same rule migrate_052 sets for the column."""
    row = cq.build_question_view([
        _session(1, 1, [_question(qtype='multiple_choice', answers=[_answer(True)])]),
    ])[0]
    assert row['confidence_mean'] is None
    assert row['confidence_n'] == 0
    assert row['unsure_count'] == 0


# --- the route --------------------------------------------------------------

QUIZ = {'questions': [
    {'text': 'Frage eins', 'options': ['richtig', 'falsch'], 'correct': [0]},
]}


def _seed_attempt(scored=0, score=0):
    """One finished session WITH a logged answer.

    The answer row is not optional decoration: _checkpoint_question_review groups by
    logged answers, so a session without them carries no per-question data at all and
    contributes nothing to the question view. Sessions written before the answer log
    existed (pre-migrate_047) are invisible here for the same reason -- correctly, as
    there is nothing to say about their questions.
    """
    student_id = models.create_student('Test', 'Schueler', 'qviewtest', 'pw123')
    klasse_id = models.create_klasse('Chemie11')
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task('Atommodelle', '', '', 'Chemie', '11/12', 'pflicht')
    subtask_id = models.create_subtask(
        task_id, 'Checkpoint 1.4', reihenfolge=0, quiz_json=json.dumps(QUIZ),
        checkpoint_type='quiz', kern_standard_tag='kern')
    models.assign_task_to_student(student_id, klasse_id, task_id)
    models.create_checkpoint_answer(
        student_id, subtask_id, 'sess-qview', question_index=0, attempt_no=1,
        answer_text='[1]', correct=False, feedback='Nicht richtig.', grader='mc')
    models.create_checkpoint_attempt(
        student_id, checkpoint_id=subtask_id, module_id=task_id, checkpoint_type='quiz',
        kern_standard_tag='kern', score=score, quiz_snapshot_json=json.dumps(QUIZ),
        question_scores_json=json.dumps({'0': scored}), session_uid='sess-qview')
    return student_id, subtask_id


def test_tab_defaults_to_sessions(as_admin):
    _seed_attempt()
    body = as_admin.get('/admin/checkpoint-pruefung').get_data(as_text=True)
    assert 'checkpoint-tab' in body
    assert 'Checkpoint-Sitzung(en)' in body


def test_question_tab_renders_the_question_view(as_admin):
    _seed_attempt()
    body = as_admin.get('/admin/checkpoint-pruefung?ansicht=fragen').get_data(as_text=True)
    assert 'Frage 1' in body
    assert 'Checkpoint-Sitzung(en)' not in body, \
        'the session batch bar belongs to the other tab'


def test_the_question_tab_writes_nothing(as_admin):
    """Phase 1 is read-only: opening the view must not be able to touch a grade."""
    _seed_attempt(scored=0, score=0)
    before = models.get_checkpoint_reviews()
    as_admin.get('/admin/checkpoint-pruefung?ansicht=fragen')
    after = models.get_checkpoint_reviews()
    assert [a['score'] for a in before] == [a['score'] for a in after]
    assert [a.get('teacher_score') for a in before] == [a.get('teacher_score') for a in after]


def test_tab_links_keep_the_current_filters(as_admin):
    _, subtask_id = _seed_attempt()
    body = as_admin.get(
        f'/admin/checkpoint-pruefung?checkpoint_id={subtask_id}&offen=1'
    ).get_data(as_text=True)
    tab = re.search(r'href="([^"]*ansicht=fragen[^"]*)"', body)
    assert tab, 'no link to the Fragen tab'
    assert f'checkpoint_id={subtask_id}' in tab.group(1)
    assert 'offen=1' in tab.group(1)
