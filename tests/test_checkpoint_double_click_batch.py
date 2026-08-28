"""Batch-correcting Doppelklick sessions from the review UI.

The single-session correction already existed; what these cover is doing it for a
whole selection at once and having the corrected sessions leave the "nur
ungeprüfte" queue, so the page stops showing work that is already dealt with.

Two rules the batch is built around, and most of these tests exist to pin them:
  - it never touches a grade or a note the teacher set by hand
  - it only acts where the score would actually change; a flagged duplicate that
    costs nothing is left in the queue for a human to look at
"""
import json

import pytest

import app as app_module
import models


CHECKPOINT_QUIZ = {
    "questions": [
        {"type": "short_answer", "text": "Erkläre den Aufbau des Atoms.",
         "rubric": "Kern mit Protonen und Neutronen, Hülle mit Elektronen."},
    ]
}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    other_klasse_id = models.create_klasse("11d")
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=0,
        quiz_json=json.dumps(CHECKPOINT_QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern",
    )

    students = {}
    for key, (nachname, vorname, user, klasse) in {
        "kaya": ("Muster", "Kaya", "happypanda", klasse_id),
        "nils": ("Beispiel", "Nils", "bravotiger", klasse_id),
        "outsider": ("Fremd", "Ada", "quickfox", other_klasse_id),
    }.items():
        student_id = models.create_student(nachname, vorname, user, "bacado42")
        models.add_student_to_klasse(student_id, klasse)
        students[key] = student_id

    return {"klasse_id": klasse_id, "other_klasse_id": other_klasse_id,
            "task_id": task_id, "subtask_id": subtask_id, "students": students}


def _session(data, student_id, session_uid, texts, correct=True, score=2):
    """One checkpoint session for one student, `texts` one logged answer each."""
    for index, text in enumerate(texts):
        models.create_checkpoint_answer(
            student_id, data["subtask_id"], session_uid,
            question_index=0, attempt_no=index + 1, answer_text=text,
            correct=correct, feedback="Passt.", grader="llm",
            llm_model="Qwen/Qwen3-32B-FP8", prompt_version="checkpoint:abc12345",
        )
    return models.create_checkpoint_attempt(
        student_id, data["subtask_id"], data["task_id"], "quiz", "kern",
        score=score, attempt_count=len(texts), hint_count=0,
        quiz_snapshot_json=json.dumps(CHECKPOINT_QUIZ), session_uid=session_uid,
    )


def _double_click(data, student_id, session_uid):
    """A session worth 3 that a resend turned into a 2 -- the case to correct."""
    return _session(data, student_id, session_uid,
                    ["Kern und Hülle", "Kern und Hülle"], correct=True, score=2)


def _correct_url():
    return "/admin/checkpoint-pruefung/doppelklick-korrigieren"


def _attempt(attempt_id):
    with models.db_session() as conn:
        return dict(conn.execute("SELECT * FROM checkpoint_attempt WHERE id = ?",
                                 (attempt_id,)).fetchone())


# ------------------------------------------------------------ what gets written

def test_batch_applies_the_score_without_the_double_click(data, as_admin):
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    row = _attempt(attempt_id)
    assert row["teacher_score"] == 3
    assert row["teacher_note"] == app_module.DOUBLE_CLICK_NOTE
    assert row["reviewed_at"] is not None


def test_corrected_sessions_leave_the_open_queue(data, as_admin):
    """The point of the review mark: the cleaned-up sessions stop showing under
    "nur ungeprüfte", which is what makes the page usable again."""
    _double_click(data, data["students"]["kaya"], "sess-1")
    assert len(models.get_checkpoint_reviews(unreviewed_only=True)) == 1

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    assert models.get_checkpoint_reviews(unreviewed_only=True) == []
    assert len(models.get_checkpoint_reviews()) == 1  # still there, just reviewed


def test_batch_notes_the_flagged_answers_for_prompt_tuning(data, as_admin):
    """The duplicate answers get the note too, so later calibration analysis can
    tell "the KI judged wrong" apart from "the student clicked twice"."""
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]
    noted = [a for a in answers if a["teacher_note"] == app_module.DOUBLE_CLICK_NOTE]
    assert len(noted) == 1                      # only the resend, not the original
    assert noted[0]["attempt_no"] == 2


def test_batch_leaves_the_calibration_verdict_empty(data, as_admin):
    """A double-click is not a grading error. Auto-filling teacher_verdict would
    put noise into the very data that field exists to collect."""
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    answers = models.get_checkpoint_answers_for_attempts([attempt_id])[attempt_id]
    assert all(a["teacher_verdict"] is None for a in answers)


# ------------------------------------------------------- what it refuses to touch

def test_batch_never_overwrites_a_grade_the_teacher_set(data, as_admin):
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")
    models.set_checkpoint_teacher_review(attempt_id, 2, "Bewusst so", "", 1)

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    row = _attempt(attempt_id)
    assert row["teacher_score"] == 2
    assert row["teacher_note"] == "Bewusst so"


def test_batch_keeps_the_rueckmeldung_already_written(data, as_admin):
    """The batch writes the grade, not the whole review -- a Rueckmeldung the
    student is meant to read must survive a cleanup pass."""
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_attempt SET student_feedback = ? WHERE id = ?",
                     ("Schau dir Frage 2 nochmal an.", attempt_id))

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    assert _attempt(attempt_id)["student_feedback"] == "Schau dir Frage 2 nochmal an."
    assert _attempt(attempt_id)["teacher_score"] == 3


def test_a_duplicate_that_costs_no_point_is_left_in_the_queue(data, as_admin):
    """Both attempts wrong: the question scores 0 either way, so there is nothing
    to correct. It stays open rather than being silently marked reviewed."""
    attempt_id = _session(data, data["students"]["kaya"], "sess-1",
                          ["Weiss nicht", "Weiss nicht"], correct=False, score=0)

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    row = _attempt(attempt_id)
    assert row["teacher_score"] is None
    assert row["reviewed_at"] is None
    assert len(models.get_checkpoint_reviews(unreviewed_only=True)) == 1


def test_a_session_without_duplicates_is_untouched(data, as_admin):
    attempt_id = _session(data, data["students"]["kaya"], "sess-1",
                          ["Kern und Hülle"], correct=True, score=3)

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    assert _attempt(attempt_id)["reviewed_at"] is None


def test_a_reset_session_is_not_corrected(data, as_admin):
    """Superseded rows are the pre-reset record. Grading them would put a score on
    a session that no longer counts."""
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")
    models.supersede_checkpoint_attempts([attempt_id])

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"],
                                        "verlauf": "1"})

    assert _attempt(attempt_id)["teacher_score"] is None


# -------------------------------------------------------------------- selection

def test_batch_respects_the_class_filter(data, as_admin):
    inside = _double_click(data, data["students"]["kaya"], "sess-1")
    outside = _double_click(data, data["students"]["outsider"], "sess-2")

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    assert _attempt(inside)["teacher_score"] == 3
    assert _attempt(outside)["teacher_score"] is None


def test_per_student_scope_spares_the_classmate(data, as_admin):
    """Scope (a): the same route with student_id pinned."""
    kaya = _double_click(data, data["students"]["kaya"], "sess-1")
    nils = _double_click(data, data["students"]["nils"], "sess-2")

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"],
                                        "student_id": data["students"]["kaya"]})

    assert _attempt(kaya)["teacher_score"] == 3
    assert _attempt(nils)["teacher_score"] is None


def test_batch_covers_every_session_of_the_selection(data, as_admin):
    ids = [_double_click(data, data["students"]["kaya"], f"sess-{n}") for n in range(3)]

    as_admin.post(_correct_url(), data={"klasse_id": data["klasse_id"]})

    assert [_attempt(i)["teacher_score"] for i in ids] == [3, 3, 3]


def test_unfiltered_batch_is_refused(data, as_admin):
    """Same guard as the bulk reset: without a filter this would regrade every
    checkpoint in the database from one click."""
    attempt_id = _double_click(data, data["students"]["kaya"], "sess-1")

    response = as_admin.post(_correct_url(), data={}, follow_redirects=True)

    assert _attempt(attempt_id)["teacher_score"] is None
    assert "ungefiltertes Korrigieren ist nicht möglich" in response.get_data(as_text=True)


# ---------------------------------------------------------------------- the page

def test_page_offers_the_batch_button_only_when_filtered(data, as_admin):
    _double_click(data, data["students"]["kaya"], "sess-1")

    unfiltered = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Doppelklicks korrigieren" not in unfiltered

    filtered = as_admin.get(
        f"/admin/checkpoint-pruefung?klasse_id={data['klasse_id']}").get_data(as_text=True)
    assert "Alle 1 Doppelklicks korrigieren" in filtered


def test_per_student_button_appears_only_from_two_sessions(data, as_admin):
    """One flagged session needs no batch -- the Speichern button above it already
    does the job, and a "batch" of one is just a confusing second way to press it."""
    _double_click(data, data["students"]["kaya"], "sess-1")
    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Doppelklicks von Kaya" not in page

    _double_click(data, data["students"]["kaya"], "sess-2")
    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Alle 2 Doppelklicks von Kaya korrigieren" in page


def test_unfiltered_page_says_why_the_button_is_missing(data, as_admin):
    """The guard is right, hiding it silently was not: the badge advertises the
    Doppelklicks, so the page has to say how to get at them."""
    _double_click(data, data["students"]["kaya"], "sess-1")

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "wären korrigierbar" in page
    assert "zuerst nach Klasse, Schüler oder Checkpoint filtern" in page


def test_no_hint_when_there_is_nothing_to_correct(data, as_admin):
    _session(data, data["students"]["kaya"], "sess-1", ["Kern und Hülle"], score=3)

    page = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "wären korrigierbar" not in page
