"""Checkpoint questions carry a fixed id; every write files its row under it.

Why: stored data keyed by position slides onto the wrong question when one is
deleted from the start or middle (task_plan.md § Feste Frage-IDs). These tests
cover the id rule on the quiz write paths and the write side (Phase C.1/C.2/C.4).
"""
import json
import re

import pytest

import models
from import_task import ValidationError, overwrite_task_from_import


def q(text, **extra):
    return dict({"type": "short_answer", "text": text, "rubric": "r"}, **extra)


def quiz(*questions):
    return json.dumps({"questions": list(questions)})


def ids_of(subtask_id):
    return [x.get("id") for x in models.quiz_questions(models.get_subtask(subtask_id)["quiz_json"])]


@pytest.fixture
def cp(db):
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11", "")
    cp_id = models.create_subtask(task_id, "### 1.4 - Test", reihenfolge=0,
                                  quiz_json=quiz(q("A"), q("B"), q("C")),
                                  checkpoint_type="quiz", kern_standard_tag="kern")
    student = models.create_student("Adler", "Kim", "u0", "pw")
    return {"task": task_id, "cp": cp_id, "student": student}


def sit(cp, scores=None):
    """A finished sitting on today's quiz, as the student route writes it."""
    snapshot = models.get_subtask(cp["cp"])["quiz_json"]
    scores = scores or {"0": 3, "1": 2, "2": 3}
    counted = [v for v in scores.values() if v is not None]
    return models.create_checkpoint_attempt(
        cp["student"], cp["cp"], cp["task"], "quiz", "kern", score=min(counted or [0]),
        quiz_snapshot_json=snapshot,
        question_scores_json=json.dumps(scores))


def by_id(attempt_id, column="question_scores_by_id_json"):
    with models.db_session() as conn:
        raw = conn.execute(f"SELECT {column} FROM checkpoint_attempt WHERE id = ?",
                           (attempt_id,)).fetchone()[0]
    return json.loads(raw) if raw else None


# ---- id rule on the quiz write paths (C.4) ----

def test_new_checkpoint_gets_ids_ordinary_quiz_does_not(cp):
    assert ids_of(cp["cp"]) == ["f1", "f2", "f3"]
    plain = models.create_subtask(cp["task"], "### Übung", reihenfolge=1, quiz_json=quiz(q("A")))
    assert ids_of(plain) == [None]


def test_given_ids_are_kept_and_missing_ones_avoid_them(db):
    task_id = models.create_task("T", "", "", "Chemie", "11", "")
    sub = models.create_subtask(task_id, "x", quiz_json=quiz(q("A"), q("B", id="f1")),
                                checkpoint_type="quiz", kern_standard_tag="kern")
    assert ids_of(sub) == ["f1-1", "f1"]


@pytest.mark.parametrize("bad, message", [
    ([q("A", id="F1")], "nur Kleinbuchstaben"),
    ([q("A", id="a"), q("B", id="a")], "doppelt"),
])
def test_malformed_ids_are_refused(db, bad, message):
    task_id = models.create_task("T", "", "", "Chemie", "11", "")
    with pytest.raises(models.QuizIdError, match=message):
        models.create_subtask(task_id, "x", quiz_json=quiz(*bad),
                              checkpoint_type="quiz", kern_standard_tag="kern")


def test_without_sittings_a_missing_id_is_filled_in(cp):
    assert models.check_checkpoint_quiz_ids(cp["cp"], quiz(q("A"), q("neu"))) is None


def test_with_sittings_every_question_needs_its_id(cp):
    sit(cp)
    problem = models.check_checkpoint_quiz_ids(
        cp["cp"], quiz(q("A", id="f1"), q("neu"), q("C", id="f3")))
    assert "Frage 2 ohne id" in problem
    # An unfinished sitting (answers only) counts too.
    other = models.create_subtask(cp["task"], "### 1.5", reihenfolge=1, quiz_json=quiz(q("A")),
                                  checkpoint_type="quiz", kern_standard_tag="kern")
    models.create_checkpoint_answer(cp["student"], other, "s9", 0, 1, "x", True, "", "llm")
    assert models.check_checkpoint_quiz_ids(other, quiz(q("A"))) is not None


def test_removed_ids_may_not_come_back(cp):
    problem = models.check_checkpoint_quiz_ids(
        cp["cp"], json.dumps({"entfernte_ids": ["f2"], "questions": [q("A", id="f1"), q("neu", id="f2")]}))
    assert "nicht wieder vergeben" in problem


def test_with_sittings_a_question_leaves_only_through_entfernte_ids(cp):
    sit(cp)
    gone = [q("A", id="f1"), q("C", id="f3")]
    assert "f2 fehlt" in models.check_checkpoint_quiz_ids(cp["cp"], quiz(*gone))
    listed = json.dumps({"entfernte_ids": ["f2"], "questions": gone})
    assert models.check_checkpoint_quiz_ids(cp["cp"], listed) is None


def test_entfernte_ids_survive_an_edit_that_drops_them(cp):
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET quiz_json = ? WHERE id = ?", (json.dumps(
            {"entfernte_ids": ["f2"], "questions": [q("A", id="f1"), q("C", id="f3")]}), cp["cp"]))
        stored = models.checkpoint_quiz_with_ids(conn, cp["cp"], quiz(q("A", id="f1"), q("neu")))
    stored = json.loads(stored)
    assert stored["entfernte_ids"] == ["f2"]
    assert [x["id"] for x in stored["questions"]] == ["f1", "f2-1"]   # f2 stays retired


def test_editor_refuses_and_saves_nothing(cp, as_admin):
    sit(cp)
    before = models.get_subtask(cp["cp"])["quiz_json"]
    token = re.search(r'name="csrf-token" content="([^"]+)"',
                      as_admin.get("/admin").get_data(as_text=True)).group(1)
    as_admin.post(f"/admin/thema/{cp['task']}/aufgaben", data={
        "subtasks[]": ["### 1.4 - Test"], "quiz_json[]": [quiz(q("A"), q("B"))],
        "checkpoint_type[]": ["quiz"], "kern_standard_tag[]": ["kern"], "csrf_token": token,
    })
    with as_admin.session_transaction() as sess:
        flashes = [m for _, m in sess.get("_flashes", [])]
    assert any("ohne id" in m for m in flashes), flashes
    assert models.get_subtask(cp["cp"])["quiz_json"] == before


def test_import_refuses_before_writing_anything(cp):
    sit(cp)
    task = {"name": "Umbenannt", "beschreibung": "", "fach": "Chemie", "stufe": "11",
            "subtasks": [{"beschreibung": "### 1.4 - Test", "checkpoint_type": "quiz",
                          "kern_standard_tag": "kern", "quiz": {"questions": [q("A")]}}]}
    with pytest.raises(ValidationError, match="Aufgabe 1: Frage 1 ohne id"):
        overwrite_task_from_import(cp["task"], {"task": task})
    assert models.get_task(cp["task"])["name"] == "1 - Atommodelle"


# ---- write side (C.2) ----

def test_answer_is_filed_under_its_question_id(cp):
    question = models.quiz_questions(models.get_subtask(cp["cp"])["quiz_json"])[1]
    logged = models.create_checkpoint_answer(cp["student"], cp["cp"], "s1", 1, 1, "x",
                                             True, "", "llm", question=question)
    with models.db_session() as conn:
        assert conn.execute("SELECT question_id FROM checkpoint_answer WHERE id = ?",
                            (logged["id"],)).fetchone()[0] == "f2"


def test_scores_are_written_by_id_too(cp):
    attempt = sit(cp, {"0": 3, "1": None, "2": 2})
    assert by_id(attempt) == {"f1": 3, "f2": None, "f3": 2}

    models.update_checkpoint_attempt_scores(attempt, {"0": 3, "1": 0, "2": 2}, 0,
                                            manual_scores={"1": 0})
    assert by_id(attempt) == {"f1": 3, "f2": 0, "f3": 2}
    assert by_id(attempt, "question_scores_manual_by_id_json") == {"f2": 0}


def test_scores_follow_the_sittings_snapshot_not_todays_quiz(cp):
    attempt = sit(cp)
    # A deleted today: position 0 is B now. The sitting's own snapshot still says
    # position 0 was A, so a later rescore must stay on f1.
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET quiz_json = ? WHERE id = ?",
                     (quiz(q("B", id="f2"), q("C", id="f3")), cp["cp"]))
    models.update_checkpoint_attempt_scores(attempt, {"0": 0, "1": 2, "2": 3}, 0)
    assert by_id(attempt) == {"f1": 0, "f2": 2, "f3": 3}


def test_flag_takes_its_id_from_the_sitting_or_todays_quiz(cp):
    attempt = sit(cp)
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET quiz_json = ? WHERE id = ?",
                     (quiz(q("B", id="f2"), q("C", id="f3")), cp["cp"]))
    on_sitting = models.create_checkpoint_flag(cp["cp"], 0, "teacher", status="nachbesserung",
                                               checkpoint_attempt_id=attempt)
    on_question = models.create_checkpoint_flag(cp["cp"], 0, "teacher", status="frage_kaputt")
    explicit = models.create_checkpoint_flag(cp["cp"], 0, "student", question_id="f3")
    with models.db_session() as conn:
        got = {r["id"]: r["question_id"] for r in conn.execute("SELECT id, question_id FROM checkpoint_flag")}
    assert got == {on_sitting: "f1", on_question: "f2", explicit: "f3"}


# ---- read side (C.3/C.5): a quiz edited after the sitting ----

def set_quiz(cp, *questions, removed=()):
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET quiz_json = ? WHERE id = ?", (json.dumps(
            {"entfernte_ids": list(removed), "questions": list(questions)}), cp["cp"]))


A, B, C = q("A", id="f1"), q("B", id="f2"), q("C", id="f3")


def overview_cells(cp, attempt):
    """The overview's cells, via grading_window (same rules as the window page)."""
    import grading_window
    subtask = models.get_subtask(cp["cp"])
    questions = models.quiz_questions(subtask["quiz_json"])
    units, _ = grading_window.expected_units(
        [{"id": cp["cp"], "checkpoint_type": "quiz", "kern_standard_tag": "kern",
          "question_ids": [x["id"] for x in questions]}],
        models.get_excluded_questions([cp["cp"]]))
    row = models.get_checkpoint_attempt(attempt)
    rows = grading_window.build_noten(
        [{"id": cp["student"]}], units,
        {cp["student"]: {"attempts": {cp["cp"]: row},
                         "scores": {cp["cp"]: models.attempt_scores_by_id(row)}}})
    return [c["punkte"] for c in rows[0]["cells"]]


@pytest.mark.parametrize("today, removed, effective, cells", [
    ([B, C], ["f1"], 2, [2, 3]),          # deleted at the start: B keeps its 2, not A's 0
    ([A, C], ["f2"], 0, [0, 3]),          # deleted in the middle
    ([A, B], ["f3"], 0, [0, 2]),          # deleted at the end
    ([C, A, B], [], 0, [3, 0, 2]),        # reordered
])
def test_points_stay_with_their_question(cp, today, removed, effective, cells):
    attempt = sit(cp, {"0": 0, "1": 2, "2": 3})
    set_quiz(cp, *today, removed=removed)
    row = models.get_checkpoint_attempt(attempt)
    assert models.effective_checkpoint_score(row) == effective
    assert overview_cells(cp, attempt) == cells


def test_a_reworded_question_keeps_counting(cp):
    attempt = sit(cp, {"0": 3, "1": 0, "2": 3})
    set_quiz(cp, A, q("B, genauer gefasst", id="f2"), C)
    assert models.effective_checkpoint_score(models.get_checkpoint_attempt(attempt)) == 0
    assert overview_cells(cp, attempt) == [3, 0, 3]


def test_exclusion_follows_the_question_not_the_position(cp):
    attempt = sit(cp, {"0": 3, "1": 0, "2": 3})
    models.set_question_excluded(cp["cp"], 1, True)          # B
    set_quiz(cp, B, C, removed=["f1"])                         # A gone, B now first
    assert models.get_excluded_questions([cp["cp"]])[cp["cp"]].at(0)["question_id"] == "f2"
    # Neither A (removed) nor B (excluded) counts: only C's 3 is left.
    assert models.effective_checkpoint_score(models.get_checkpoint_attempt(attempt)) == 3


def test_a_flag_follows_its_question(cp):
    attempt = sit(cp, {"0": 3, "1": None, "2": 3})
    models.create_checkpoint_flag(cp["cp"], 1, "student", student_id=cp["student"],
                                  checkpoint_attempt_id=attempt, status="abgelehnt")
    set_quiz(cp, B, C, removed=["f1"])
    owed = models.get_checkpoints_awaiting_retry(cp["student"])
    assert [x["nr"] for x in owed[cp["cp"]]] == [1]          # B, today first
    set_quiz(cp, A, C, removed=["f2"])
    assert not models.get_checkpoints_awaiting_retry(cp["student"])   # B gone: owes nothing
    assert not models.checkpoint_score_is_provisional({"id": attempt})


def test_resume_finds_an_answer_after_the_quiz_moved(cp):
    question_b = models.quiz_questions(models.get_subtask(cp["cp"])["quiz_json"])[1]
    models.create_checkpoint_answer(cp["student"], cp["cp"], "u1", 1, None, "x", True, "",
                                    "llm", question=question_b)
    set_quiz(cp, B, C, removed=["f1"])
    resumed = models.resume_unfinished_checkpoint_session(cp["student"], cp["cp"])
    assert list(resumed["questions"]) == [0]
    assert resumed["questions"][0]["solved"]


def test_review_answers_sit_at_the_sittings_position(cp):
    """Answered while B was second; the snapshot taken at the end already had A
    removed. The answer belongs to B wherever B sits in that snapshot."""
    question_b = models.quiz_questions(models.get_subtask(cp["cp"])["quiz_json"])[1]
    models.create_checkpoint_answer(cp["student"], cp["cp"], "u2", 1, None, "x", True, "",
                                    "llm", question=question_b)
    set_quiz(cp, B, C, removed=["f1"])
    attempt = models.create_checkpoint_attempt(
        cp["student"], cp["cp"], cp["task"], "quiz", "kern", score=3,
        quiz_snapshot_json=models.get_subtask(cp["cp"])["quiz_json"], session_uid="u2",
        question_scores_json=json.dumps({"0": 3, "1": 3}))
    answers = models.get_checkpoint_answers_for_attempt(attempt)
    assert [(a["question_index"], a["question_id"]) for a in answers] == [(0, "f2")]


def test_export_names_the_question_id(cp, as_admin):
    questions = models.quiz_questions(models.get_subtask(cp["cp"])["quiz_json"])
    for i, question in enumerate(questions):
        models.create_checkpoint_answer(cp["student"], cp["cp"], "u3", i, None, "x", True, "",
                                        "llm", question=question)
    attempt = sit(cp)
    models.attach_checkpoint_session_to_attempt("u3", attempt)
    export = json.loads(as_admin.get("/admin/checkpoint-pruefung/export.json").get_data(as_text=True))
    assert [x["id"] for x in export["sessions"][0]["fragen"]] == ["f1", "f2", "f3"]
