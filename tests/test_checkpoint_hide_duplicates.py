"""Hiding Doppelklick sessions from the review listing.

A view filter, not a write: `ohne_doppelklick=1` drops flagged sessions from what
is shown so the page can be read for something else. Nothing is stored, nothing is
graded, and unticking the box brings them straight back.

The part worth testing hardest is not the hiding. `has_duplicates` is derived from
the answer log rather than a column, so the hide lives in the app layer -- and
every route that re-derives a selection server-side has to honour it, or a button
labelled "alle angezeigten" would act on rows the teacher cannot see.
"""
import json

import pytest

import app as app_module
import models


QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern und Hülle."},
    ]
}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    students = {}
    for key, (nachname, vorname, user) in {
        "kaya": ("Muster", "Kaya", "happypanda"),
        "nils": ("Beispiel", "Nils", "bravotiger"),
    }.items():
        student_id = models.create_student(nachname, vorname, user, "bacado42")
        models.add_student_to_klasse(student_id, klasse_id)
        students[key] = student_id
    return {"klasse_id": klasse_id, "task_id": task_id,
            "subtask_id": subtask_id, "students": students}


def _session(data, student_id, session_uid, texts, score=2):
    for index, text in enumerate(texts):
        models.create_checkpoint_answer(
            student_id, data["subtask_id"], session_uid,
            question_index=0, attempt_no=index + 1, answer_text=text,
            correct=True, feedback="Passt.", grader="llm",
            llm_model="Qwen/Qwen3-32B-FP8",
        )
    return models.create_checkpoint_attempt(
        student_id, data["subtask_id"], data["task_id"], "quiz", "kern",
        score=score, attempt_count=len(texts), hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid=session_uid,
    )


def _flagged(data, student_id, session_uid="sess-dup"):
    return _session(data, student_id, session_uid, ["Kern und Hülle", "Kern und Hülle"])


def _clean(data, student_id, session_uid="sess-clean"):
    return _session(data, student_id, session_uid, ["Kern und Hülle"], score=3)


def _attempt(attempt_id):
    with models.db_session() as conn:
        return dict(conn.execute("SELECT * FROM checkpoint_attempt WHERE id = ?",
                                 (attempt_id,)).fetchone())


# ------------------------------------------------------------------- the listing

def test_flagged_sessions_disappear_from_the_listing(data, as_admin):
    _flagged(data, data["students"]["kaya"])
    _clean(data, data["students"]["nils"])

    page = as_admin.get("/admin/checkpoint-pruefung?ohne_doppelklick=1").get_data(as_text=True)

    assert "Nils Beispiel" in page
    assert "Kaya Muster" not in page


def test_they_come_back_without_the_toggle(data, as_admin):
    _flagged(data, data["students"]["kaya"])

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "Kaya Muster" in page


def test_the_page_says_how_many_it_hid(data, as_admin):
    """A list that silently shrinks is worse than one that explains itself."""
    _flagged(data, data["students"]["kaya"])
    _clean(data, data["students"]["nils"])

    page = as_admin.get("/admin/checkpoint-pruefung?ohne_doppelklick=1").get_data(as_text=True)

    assert "1 Doppelklick-Sitzung(en) ausgeblendet" in page


def test_hiding_writes_nothing(data, as_admin):
    """The whole point of a view filter: no grade, no note, no review mark."""
    attempt_id = _flagged(data, data["students"]["kaya"])

    as_admin.get("/admin/checkpoint-pruefung?ohne_doppelklick=1")

    row = _attempt(attempt_id)
    assert row["teacher_score"] is None
    assert row["teacher_note"] is None
    assert row["reviewed_at"] is None
    assert len(models.get_checkpoint_reviews()) == 1


# ------------------------------------------- every server-side selection honours it

def test_a_hidden_session_is_not_bulk_reset(data, as_admin):
    """The reset button says "alle angezeigten". It must mean it -- resetting a row
    the teacher cannot see is the one mistake here that is tedious to undo."""
    hidden = _flagged(data, data["students"]["kaya"])
    shown = _clean(data, data["students"]["nils"])

    as_admin.post("/admin/checkpoint-pruefung/zuruecksetzen",
                  data={"klasse_id": data["klasse_id"], "ohne_doppelklick": "1"})

    assert _attempt(hidden)["superseded_at"] is None
    assert _attempt(shown)["superseded_at"] is not None


def test_a_hidden_session_is_not_batch_corrected(data, as_admin):
    hidden = _flagged(data, data["students"]["kaya"])

    as_admin.post("/admin/checkpoint-pruefung/doppelklick-korrigieren",
                  data={"klasse_id": data["klasse_id"], "ohne_doppelklick": "1"})

    assert _attempt(hidden)["teacher_score"] is None


def test_a_hidden_session_is_not_batch_dismissed(data, as_admin):
    hidden = _flagged(data, data["students"]["kaya"])

    as_admin.post("/admin/checkpoint-pruefung/doppelklick-korrigieren",
                  data={"klasse_id": data["klasse_id"], "modus": "abhaken",
                        "ohne_doppelklick": "1"})

    assert _attempt(hidden)["reviewed_at"] is None


def test_the_exports_match_what_is_on_screen(data, as_admin):
    _flagged(data, data["students"]["kaya"])
    _clean(data, data["students"]["nils"])

    csv = as_admin.get(
        "/admin/checkpoint-pruefung/export.csv?ohne_doppelklick=1").get_data(as_text=True)
    payload = as_admin.get(
        "/admin/checkpoint-pruefung/export.json?ohne_doppelklick=1").get_json()

    assert "Kaya Muster" not in csv
    assert "Nils Beispiel" in csv
    assert [s["student"] for s in payload["sessions"]] == ["Nils Beispiel"]


def test_the_batch_buttons_vanish_while_hiding(data, as_admin):
    """Consistency: what the buttons offer is what the page shows."""
    _flagged(data, data["students"]["kaya"])

    page = as_admin.get(
        f"/admin/checkpoint-pruefung?klasse_id={data['klasse_id']}"
        "&ohne_doppelklick=1").get_data(as_text=True)

    assert "Doppelklicks korrigieren" not in page
    assert "als geprüft abhaken" not in page
    # The count badge, not the checkbox label that also contains the phrase.
    assert "1 mit Doppelklick-Verdacht" not in page
