"""Regression tests for the warmup question pool filter.

get_warmup_question_pool() only admits questions from a quiz the student has
actually sat (a quiz_attempt row exists). It must exclude:
- short_answer (too slow for warmup)
- long_answer (when implemented)
- Einführung subtasks (is_intro — questions don't make sense out of context)
- quizzes that were never attempted, even in a topic marked complete
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


def _student_task_id(student_id, task_id):
    with models.db_session() as conn:
        return conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        ).fetchone()["id"]


def _record_attempt(student_id, task_id, subtask_id=None):
    """Log a quiz attempt -- the pool only admits quizzes the student has sat."""
    models.save_quiz_attempt(
        _student_task_id(student_id, task_id), 1, 1, "[]", subtask_id=subtask_id)


def _completed_topic_with_quiz(student_id, klasse_id, quiz):
    """Helper: create a topic, assign, mark complete, log a topic-quiz attempt."""
    task_id = models.create_task(
        "Testthema", "", "", "MBI", "5", "",
        quiz_json=json.dumps(quiz),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        conn.execute(
            "UPDATE student_task SET abgeschlossen = 1 WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        )
    _record_attempt(student_id, task_id)
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


def _add_subtask_with_quiz(task_id, reihenfolge, quiz, is_intro=0):
    """Insert a subtask with a quiz at the given position. Returns subtask_id."""
    with models.db_session() as conn:
        cur = conn.execute(
            "INSERT INTO subtask (task_id, beschreibung, reihenfolge, path, quiz_json, is_intro) "
            "VALUES (?, '', ?, 'bergweg', ?, ?)",
            (task_id, reihenfolge, json.dumps(quiz), is_intro),
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
    """An Einführung is excluded by its is_intro flag, not by its position."""
    student_id = models.create_student("Test", "Schüler", "introtest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, task_id)

    # Intro sits at position 2 -- the old reihenfolge > MIN filter would miss it
    first_id = _add_subtask_with_quiz(task_id, reihenfolge=0, quiz=SIMPLE_QUIZ)
    intro_id = _add_subtask_with_quiz(task_id, reihenfolge=1, quiz=SIMPLE_QUIZ, is_intro=1)
    regular_id = _add_subtask_with_quiz(task_id, reihenfolge=2, quiz=SIMPLE_QUIZ)

    for sid in (first_id, intro_id, regular_id):
        _complete_subtask(student_id, task_id, sid)
        _record_attempt(student_id, task_id, subtask_id=sid)

    pool = models.get_warmup_question_pool(student_id)
    subtask_ids = {item["subtask_id"] for item in pool}

    assert intro_id not in subtask_ids
    assert first_id in subtask_ids
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
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                  quiz_json=json.dumps(quiz_with_long_answer))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        conn.execute(
            "UPDATE student_task SET abgeschlossen = 1 WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        )
    _record_attempt(student_id, task_id)

    pool = models.get_warmup_question_pool(student_id)
    types = {item["question"].get("type", "multiple_choice") for item in pool}

    assert "long_answer" not in types


# ---- Attempt gating: a quiz only enters the pool once the student has sat it ----

def test_manually_completed_topic_without_attempts_gives_no_pool(db):
    """A topic ticked complete by hand has no attempts behind it -- warming up on
    its questions would be a first encounter, not repetition."""
    student_id = models.create_student("Test", "Schüler", "handdone", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                 quiz_json=json.dumps(SIMPLE_QUIZ))
    _add_subtask_with_quiz(task_id, reihenfolge=0, quiz=SIMPLE_QUIZ)
    _add_subtask_with_quiz(task_id, reihenfolge=1, quiz=SIMPLE_QUIZ)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        conn.execute(
            "UPDATE student_task SET abgeschlossen = 1 WHERE student_id = ? AND task_id = ?",
            (student_id, task_id),
        )

    assert models.get_warmup_question_pool(student_id) == []


def test_completed_subtask_without_quiz_attempt_stays_out(db):
    """Ticking the Aufgabe done is not enough -- the quiz itself must have been sat."""
    student_id = models.create_student("Test", "Schüler", "noattempt", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    _add_subtask_with_quiz(task_id, reihenfolge=0, quiz=SIMPLE_QUIZ)
    done_id = _add_subtask_with_quiz(task_id, reihenfolge=1, quiz=SIMPLE_QUIZ)
    _complete_subtask(student_id, task_id, done_id)

    assert models.get_warmup_question_pool(student_id) == []

    _record_attempt(student_id, task_id, subtask_id=done_id)
    assert {i["subtask_id"] for i in models.get_warmup_question_pool(student_id)} == {done_id}


# ---- Class practice unlock: the deliberate exception, filtered by path/fork ----

def test_class_unlock_needs_no_attempt(db):
    """A teacher unlocking a topic for the whole class opts everyone in."""
    student_id = models.create_student("Test", "Schüler", "unlocked", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                 quiz_json=json.dumps(SIMPLE_QUIZ))
    models.set_practice_unlock_for_class(klasse_id, task_id, True)

    assert len(models.get_warmup_question_pool(student_id)) == 1


def test_class_unlock_skips_subtasks_above_the_students_path(db):
    student_id = models.create_student("Test", "Schüler", "wanderer", "pw123",
                                       lernpfad="wanderweg")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    models.set_practice_unlock_for_class(klasse_id, task_id, True)
    with models.db_session() as conn:
        conn.execute(
            "INSERT INTO subtask (task_id, beschreibung, reihenfolge, path, path_model, quiz_json) "
            "VALUES (?, '', 1, 'gipfeltour', 'skip', ?)",
            (task_id, json.dumps(SIMPLE_QUIZ)),
        )

    assert models.get_warmup_question_pool(student_id) == []


def test_class_unlock_skips_the_fork_branch_the_student_did_not_pick(db):
    student_id = models.create_student("Test", "Schüler", "forkpick", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    models.set_practice_unlock_for_class(klasse_id, task_id, True)
    with models.db_session() as conn:
        for pos, branch in ((1, "a"), (2, "b")):
            conn.execute(
                "INSERT INTO subtask (task_id, beschreibung, reihenfolge, path, quiz_json, "
                "fork_group, fork_branch) VALUES (?, '', ?, 'bergweg', ?, 'wahl1', ?)",
                (task_id, pos, json.dumps(SIMPLE_QUIZ), branch),
            )
    models.set_student_fork_choice(student_id, "wahl1", "a")

    pool = models.get_warmup_question_pool(student_id)
    with models.db_session() as conn:
        branch_of = {
            r["id"]: r["fork_branch"] for r in conn.execute(
                "SELECT id, fork_branch FROM subtask WHERE task_id = ?", (task_id,))
        }

    assert {branch_of[i["subtask_id"]] for i in pool} == {"a"}


def test_questions_tagged_above_the_students_path_are_dropped(db):
    student_id = models.create_student("Test", "Schüler", "pathq", "pw123",
                                       lernpfad="wanderweg")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)

    quiz = {"questions": [
        {"text": "Für alle?", "options": ["ja", "nein"], "correct": [0]},
        {"text": "Nur Gipfel?", "options": ["ja", "nein"], "correct": [0], "path": "gipfeltour"},
    ]}
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                 quiz_json=json.dumps(quiz))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    _record_attempt(student_id, task_id)

    pool = models.get_warmup_question_pool(student_id)

    assert [i["question"]["text"] for i in pool] == ["Für alle?"]
