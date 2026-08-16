"""Regression test: warmup/practice question serialization must not leak the
MC answer key to the client before grading. Mirrors the Quiz-Checkpoint
serializer's existing rule (_serialize_checkpoint_question), which
deliberately omits 'correct' for the same reason. Grading itself already
happens server-side (student_warmup_answer rebuilds the question from the
pool) -- this only closes the pre-answer leak in the initial page payload.
"""
from app import _serialize_question_for_js


def _pool_item(question):
    return {
        'task_id': 1, 'subtask_id': None, 'question_index': 0,
        'topic_name': 'Testthema', 'question': question,
    }


def test_multi_choice_correct_indices_not_serialized():
    item = _pool_item({
        'type': 'multiple_choice',
        'text': 'Welche sind Vögel?',
        'options': ['Adler', 'Hund', 'Ente'],
        'correct': [0, 2],
    })
    result = _serialize_question_for_js(item)

    assert 'correct' not in result
    assert result['correct_count'] == 2


def test_single_choice_correct_count_still_signals_radio_vs_checkbox():
    item = _pool_item({
        'type': 'multiple_choice',
        'text': 'Hauptstadt von Deutschland?',
        'options': ['Berlin', 'München', 'Hamburg'],
        'correct': [0],
    })
    result = _serialize_question_for_js(item)

    assert 'correct' not in result
    assert result['correct_count'] == 1


def test_fill_blank_answers_not_serialized():
    item = _pool_item({
        'type': 'fill_blank',
        'text': 'Die Hauptstadt ist ___.',
        'answers': ['Berlin', 'berlin'],
    })
    result = _serialize_question_for_js(item)

    assert 'answers' not in result
    assert 'correct' not in result
