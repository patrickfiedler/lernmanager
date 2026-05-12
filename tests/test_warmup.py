"""Regression tests for the warmup question pool filter.

get_warmup_question_pool() must exclude:
- short_answer (too slow for warmup)
- long_answer (when implemented)
- intro subtasks (first subtask per topic — questions don't make sense out of context)
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


SIMPLE_QUIZ = {"questions": [{"text": "Was ist 2+2?", "options": ["3", "4"], "correct": [1]}]}


def _add_subtask_with_quiz(task_id, reihenfolge, quiz):
    """Insert a subtask with a quiz at the given position. Returns subtask_id."""
    with models.db_session() as conn:
        cur = conn.execute(
            "INSERT INTO subtask (task_id, beschreibung, reihenfolge, path, quiz_json) VALUES (?, '', ?, 'bergweg', ?)",
            (task_id, reihenfolge, json.dumps(quiz)),
        )
        return cur.lastrowid


def _complete_subtask(student_id, task_id, subtask_id):
    with models.db_session() as conn:
        st = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        ).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO student_subtask (student_task_id, subtask_id, erledigt) VALUES (?, ?, 1)",
            (st["id"], subtask_id),
        )


def test_warmup_excludes_intro_subtask_quiz(db):
    """First subtask per topic (intro) must not appear in the pool."""
    student_id = models.create_student("Test", "Schüler", "introtest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, task_id)

    intro_id = _add_subtask_with_quiz(task_id, reihenfolge=0, quiz=SIMPLE_QUIZ)
    regular_id = _add_subtask_with_quiz(task_id, reihenfolge=1, quiz=SIMPLE_QUIZ)

    _complete_subtask(student_id, task_id, intro_id)
    _complete_subtask(student_id, task_id, regular_id)

    pool = models.get_warmup_question_pool(student_id)
    subtask_ids = {item["subtask_id"] for item in pool}

    assert intro_id not in subtask_ids
    assert regular_id in subtask_ids


def test_warmup_excludes_long_answer(db):
    """long_answer questions must be excluded from the warmup pool (TODO: implement filter)."""
    student_id = models.create_student("Test", "Schüler", "longtest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    quiz_with_long_answer = {
        "questions": [
            {"text": "Was ist 2+2?", "options": ["3", "4"], "correct": [1]},
            {"type": "long_answer", "text": "Erkläre...", "rubric": "..."},
        ]
    }
    task_id = models.create_task("Testthema", "", "", "MBI", "5/6", "pflicht",
                                  quiz_json=json.dumps(quiz_with_long_answer))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        conn.execute(
            "UPDATE student_task SET abgeschlossen = 1 WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        )

    pool = models.get_warmup_question_pool(student_id)
    types = {item["question"].get("type", "multiple_choice") for item in pool}

    assert "long_answer" not in types
