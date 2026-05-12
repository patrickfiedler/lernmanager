"""Regression tests for the warmup question pool filter.

get_warmup_question_pool() must exclude question types that can't be
graded quickly in warmup context. Currently: short_answer.
When long_answer is implemented, it must be added to this filter too.
"""
import json
import models

# A topic quiz with one of each question type
MIXED_QUIZ = {
    "questions": [
        {
            "text": "Was ist ein Virus?",
            "options": ["Software", "Hardware", "Netzwerk"],
            "correct": [0],
        },
        {
            "type": "fill_blank",
            "text": "Eine ___ schützt vor unerwünschtem Netzwerkzugriff.",
            "answers": ["Firewall"],
        },
        {
            "type": "short_answer",
            "text": "Erkläre den Unterschied zwischen Viren und Trojanern.",
            "rubric": "Student should mention self-replication (virus) vs. disguise (trojan).",
        },
    ]
}


def _completed_topic_with_quiz(student_id, klasse_id, quiz):
    """Helper: create a topic, assign to student, mark completed. Returns task_id."""
    task_id = models.create_task(
        "Testthema", "", "", "MBI", "5/6", "",
        quiz_json=json.dumps(quiz),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        conn.execute(
            "UPDATE student_task SET abgeschlossen = 1 WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        )
    return task_id


def test_warmup_includes_mc_and_fill_blank(db):
    student_id = models.create_student("Test", "Schüler", "testschueler", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    _completed_topic_with_quiz(student_id, klasse_id, MIXED_QUIZ)

    pool = models.get_warmup_question_pool(student_id)
    types = {item["question"].get("type", "multiple_choice") for item in pool}

    assert "multiple_choice" in types
    assert "fill_blank" in types


def test_warmup_excludes_short_answer(db):
    student_id = models.create_student("Test", "Schüler", "testschueler2", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    _completed_topic_with_quiz(student_id, klasse_id, MIXED_QUIZ)

    pool = models.get_warmup_question_pool(student_id)
    types = {item["question"].get("type", "multiple_choice") for item in pool}

    assert "short_answer" not in types


def test_warmup_empty_for_student_with_no_completed_topics(db):
    student_id = models.create_student("Neu", "Schüler", "neuschueler", "pw123")

    pool = models.get_warmup_question_pool(student_id)

    assert pool == []
