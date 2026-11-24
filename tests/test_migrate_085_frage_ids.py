"""migrate_085: stored checkpoint data moves from a question's position to its id.

The case it exists for (chemie + Patrick, 2026-11-24): a question deleted from the
START or MIDDLE of a checkpoint shifts every later position, so points end up on the
wrong question. The migration ties each old row to a question by its wording at the
time, and stops rather than guess.
"""
import importlib
import json
import os
import sys

import pytest

import config
import models

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrate'))
mig = importlib.import_module('migrate_085_frage_ids')


def q(text):
    return {"type": "short_answer", "text": text, "rubric": "r"}


A, B, C = q("Frage A"), q("Frage B"), q("Frage C")


@pytest.fixture
def cp(db, monkeypatch):
    monkeypatch.setattr(mig, 'DECISIONS', {})
    monkeypatch.setattr(mig, 'EXPECTED_HEADINGS', {})
    monkeypatch.setattr(mig, 'IGNORED_CHECKPOINTS', set())
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11", "")
    cp_id = models.create_subtask(task_id, "### 1.4 - Test", reihenfolge=0,
                                  quiz_json=json.dumps({"questions": [A, B, C]}),
                                  checkpoint_type="quiz", kern_standard_tag="kern")
    student = models.create_student("Adler", "Kim", "u0", "pw")
    _old_schema()
    set_quiz({"cp": cp_id}, [A, B, C])       # as before: no ids yet
    return {"task": task_id, "cp": cp_id, "student": student}


def _old_schema():
    """Turn init_db's schema back into the one this migration meets in production."""
    with models.db_session() as conn:
        conn.execute("DROP INDEX idx_checkpoint_flag_question_id")
        for table, column in (("checkpoint_attempt", "question_scores_by_id_json"),
                              ("checkpoint_attempt", "question_scores_manual_by_id_json"),
                              ("checkpoint_answer", "question_id"),
                              ("checkpoint_flag", "question_id")):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute("DROP TABLE checkpoint_question_exclusion")
        conn.execute("""CREATE TABLE checkpoint_question_exclusion (
            checkpoint_id INTEGER NOT NULL, question_index INTEGER NOT NULL,
            reason TEXT, question_text TEXT, created_at TEXT NOT NULL, created_by INTEGER,
            PRIMARY KEY (checkpoint_id, question_index))""")
        conn.execute("DROP TABLE checkpoint_question_note")
        conn.execute("""CREATE TABLE checkpoint_question_note (
            checkpoint_id INTEGER NOT NULL, question_index INTEGER NOT NULL,
            admin_id INTEGER NOT NULL, note TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (checkpoint_id, question_index, admin_id))""")


def insert(table, **values):
    """A row as the old code wrote it (models' writers know the new columns)."""
    with models.db_session() as conn:
        return conn.execute(
            f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            list(values.values())).lastrowid


def sit(cp, questions, scores):
    return insert("checkpoint_attempt", student_id=cp["student"], checkpoint_id=cp["cp"],
                  module_id=cp["task"], checkpoint_type="quiz", kern_standard_tag="kern",
                  score=0, timestamp="2026-11-01 10:00",
                  quiz_snapshot_json=json.dumps({"questions": questions}),
                  question_scores_json=json.dumps(scores))


def set_quiz(cp, questions):
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET quiz_json = ? WHERE id = ?",
                     (json.dumps({"questions": questions}), cp["cp"]))


def row(sql, *args):
    with models.db_session() as conn:
        return dict(conn.execute(sql, args).fetchone())


def by_id(attempt_id):
    """None also when the column does not exist yet: a halted run adds nothing."""
    with models.db_session() as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(checkpoint_attempt)")}
    if "question_scores_by_id_json" not in columns:
        return None
    raw = row("SELECT question_scores_by_id_json AS s FROM checkpoint_attempt WHERE id = ?",
              attempt_id)["s"]
    return json.loads(raw) if raw else None


def test_question_deleted_from_the_start_halts_until_decided(cp, monkeypatch):
    attempt = sit(cp, [A, B, C], {"0": 3, "1": 2, "2": 0})
    set_quiz(cp, [B, C])                     # A deleted: B and C move up one place

    assert mig.run() is False                # A has no match and no decision
    assert by_id(attempt) is None            # ... and nothing was written
    assert "id" not in json.loads(row("SELECT quiz_json FROM subtask WHERE id = ?", cp["cp"])["quiz_json"])["questions"][0]

    monkeypatch.setattr(mig, 'DECISIONS', {(cp["cp"], mig.text_key("Frage A")): mig.REMOVED})
    assert mig.run() is True
    # B kept its 2 and C its 0 -- by position they would now read 3 and 2.
    assert by_id(attempt) == {mig.removed_id("Frage A"): 3, "f1": 2, "f2": 0}


def test_middle_deletion_and_reordering_follow_the_wording(cp, monkeypatch):
    attempt = sit(cp, [A, B, C], {"0": 3, "1": 0, "2": 2})
    set_quiz(cp, [C, A])                     # B deleted, the rest reordered
    monkeypatch.setattr(mig, 'DECISIONS', {(cp["cp"], mig.text_key("Frage B")): mig.REMOVED})
    assert mig.run() is True
    assert by_id(attempt) == {"f2": 3, mig.removed_id("Frage B"): 0, "f1": 2}


def test_a_reworded_question_follows_the_decision(cp, monkeypatch):
    attempt = sit(cp, [A, B, C], {"0": 3, "1": 2, "2": 0})
    set_quiz(cp, [A, q("Frage B, genauer gefasst"), C])
    monkeypatch.setattr(mig, 'DECISIONS', {(cp["cp"], mig.text_key("Frage B")): 2})
    assert mig.run() is True
    assert by_id(attempt) == {"f1": 3, "f2": 2, "f3": 0}


def test_two_old_questions_on_one_new_id_halts(cp, monkeypatch):
    """Fall 7: one sitting cannot hold two scores for the same question."""
    sit(cp, [A, B, C], {"0": 3, "1": 2, "2": 0})
    set_quiz(cp, [A, q("B und C zusammen")])
    monkeypatch.setattr(mig, 'DECISIONS', {(cp["cp"], mig.text_key("Frage B")): 2,
                                           (cp["cp"], mig.text_key("Frage C")): 2})
    plan, stats, problems = mig.build_plan(_conn())
    assert any("dieselbe id" in p for p in problems)


def test_ignored_module_needs_no_decision(cp, monkeypatch):
    with models.db_session() as conn:
        conn.execute("UPDATE task SET name = '12 - Elektrolyse' WHERE id = ?", (cp["task"],))
    attempt = sit(cp, [A, B, C], {"0": 3, "1": 2, "2": 0})
    set_quiz(cp, [B, C])
    assert mig.run() is True
    assert by_id(attempt)[mig.removed_id("Frage A")] == 3


def test_legacy_key_manual_scores_answers_and_flags(cp, monkeypatch):
    attempt = sit(cp, [A, B, C], {"vorher": 0, "0": 3, "1": None, "2": 2})
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_attempt SET question_scores_manual_json = ? WHERE id = ?",
                     (json.dumps({"2": 2}), attempt))
    answer = insert("checkpoint_answer", checkpoint_attempt_id=attempt, student_id=cp["student"],
                    checkpoint_id=cp["cp"], session_uid="s1", question_index=2, attempt_no=1,
                    answer_text="x", correct=1, grader="llm", timestamp="2026-11-01 10:00")
    flag = insert("checkpoint_flag", checkpoint_id=cp["cp"], question_index=1,
                  student_id=cp["student"], checkpoint_attempt_id=attempt, source="student",
                  question_text_at_flag="Frage B", created_at="2026-11-01 10:00")
    set_quiz(cp, [C, B])                     # A deleted, B and C swapped
    monkeypatch.setattr(mig, 'DECISIONS', {(cp["cp"], mig.text_key("Frage A")): mig.REMOVED})
    assert mig.run() is True

    assert by_id(attempt) == {"vorher": 0, mig.removed_id("Frage A"): 3, "f2": None, "f1": 2}
    manual = row("SELECT question_scores_manual_by_id_json AS m FROM checkpoint_attempt "
                 "WHERE id = ?", attempt)["m"]
    assert json.loads(manual) == {"f1": 2}
    assert row("SELECT question_id FROM checkpoint_answer WHERE id = ?", answer)["question_id"] == "f1"
    assert row("SELECT question_id FROM checkpoint_flag WHERE id = ?", flag)["question_id"] == "f2"
    snap = json.loads(row("SELECT quiz_snapshot_json AS s FROM checkpoint_attempt WHERE id = ?",
                          attempt)["s"])
    assert [x["id"] for x in snap["questions"]] == [mig.removed_id("Frage A"), "f2", "f1"]
    assert [x["text"] for x in snap["questions"]] == ["Frage A", "Frage B", "Frage C"]  # untouched


def test_existing_ids_are_kept_and_a_second_run_changes_nothing(cp):
    set_quiz(cp, [dict(A, id="anregung"), B, C])
    attempt = sit(cp, [A, B, C], {"0": 3, "1": 2, "2": 0})
    assert mig.run() is True
    first = (row("SELECT quiz_json FROM subtask WHERE id = ?", cp["cp"]), by_id(attempt))
    assert [x["id"] for x in json.loads(first[0]["quiz_json"])["questions"]] == ["anregung", "f2", "f3"]
    assert mig.run() is True
    assert (row("SELECT quiz_json FROM subtask WHERE id = ?", cp["cp"]), by_id(attempt)) == first


def test_exclusion_and_note_are_rekeyed_on_the_id(cp):
    insert("checkpoint_question_exclusion", checkpoint_id=cp["cp"], question_index=2,
           question_text="Frage C", created_at="2026-11-01")
    insert("checkpoint_question_note", checkpoint_id=cp["cp"], question_index=0, admin_id=1,
           note="unklar", updated_at="2026-11-01")
    assert mig.run() is True
    assert row("SELECT question_id FROM checkpoint_question_exclusion")["question_id"] == "f3"
    assert row("SELECT question_id FROM checkpoint_question_note")["question_id"] == "f1"

    # The case the new key is for: A deleted, B now at position 0. Excluding it must
    # not collide with -- or overwrite -- the note filed under A at position 0.
    set_quiz(cp, [dict(B, id="f2"), dict(C, id="f3")])
    models.set_checkpoint_question_note(cp["cp"], 0, 1, "B auch")
    models.set_question_excluded(cp["cp"], 1, False)       # C counts again
    with models.db_session() as conn:
        notes = {r["question_id"]: r["note"] for r in conn.execute(
            "SELECT * FROM checkpoint_question_note")}
        assert conn.execute("SELECT COUNT(*) FROM checkpoint_question_exclusion").fetchone()[0] == 0
    assert notes == {"f1": "unklar", "f2": "B auch"}


def test_heading_guard(cp, monkeypatch):
    monkeypatch.setattr(mig, 'EXPECTED_HEADINGS', {cp["cp"]: "### 3.3"})
    plan, stats, problems = mig.build_plan(_conn())
    assert any("die Entscheidungen meinen" in p for p in problems)


def _conn():
    import sqlite3
    return sqlite3.connect(config.DATABASE)
