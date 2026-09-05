"""Batch rescore of ONE checkpoint question across a filtered selection.

The hazard this exists to avoid: `question_index` is not an identifier. 6 of 24 slots
in the 2026-08/09 production data carry more than one wording, so a batch keyed on
(checkpoint, index) would rescore students who answered a different question. Every
session is therefore classified against the reference WORDING, and only exact matches
are touched -- see checkpoint_questions.plan_bulk_score.

Two halves:
  * the plan (pure, no writes) -- who is in, who is out, and why,
  * the route -- preview first, write only on confirm, and never unfiltered.
"""
import json

import pytest

import app as app_module
import checkpoint_questions
import models


WORDING_A = "Erkläre den Aufbau des Atoms."
WORDING_B = "Beschreibe den Aufbau eines Atoms in eigenen Worten."


def _quiz(text):
    return {"questions": [{"type": "short_answer", "text": text,
                           "rubric": "Kern und Hülle."}]}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11s", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung", reihenfolge=0,
        quiz_json=json.dumps(_quiz(WORDING_A)), checkpoint_type="quiz",
        kern_standard_tag="kern")
    return {"klasse_id": klasse_id, "task_id": task_id, "subtask_id": subtask_id}


def _student(data, nachname):
    student_id = models.create_student(nachname, "Kaya", f"user{nachname}", "bacado42")
    models.add_student_to_klasse(student_id, data["klasse_id"])
    return student_id


def _session(data, student_id, wording=WORDING_A, score=0, correct=False,
             question_scores=None, **attempt_kwargs):
    """One finished session on question 0, with a chosen stored breakdown."""
    uid = f"sess-{student_id}"
    models.create_checkpoint_answer(
        student_id, data["subtask_id"], uid, question_index=0, attempt_no=1,
        answer_text="Kern und Hülle", correct=correct,
        feedback=None if correct else "Fehlt: Hülle", grader="llm",
        judgment_confidence=0.99)
    attempt_id = models.create_checkpoint_attempt(
        student_id, data["subtask_id"], data["task_id"], "quiz", "kern",
        score=score, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(_quiz(wording)), session_uid=uid,
        **attempt_kwargs)
    scores = {"0": score} if question_scores is None else question_scores
    models.update_checkpoint_attempt_scores(
        attempt_id, scores, app_module._consolidate_question_scores(scores))
    return attempt_id


def _plan(data, include_reviewed=False, **filters):
    sessions = app_module._build_checkpoint_sessions(
        models.get_checkpoint_reviews(**filters))
    return checkpoint_questions.plan_bulk_score(
        sessions, data["subtask_id"], 0, None,
        consolidate=app_module._consolidate_question_scores,
        include_reviewed=include_reviewed)


def _applied_names(plan):
    return sorted(row["student_name"] for row in plan["apply"])


def _skipped_names(plan, reason):
    return sorted(row["student_name"] for row in plan["skipped"].get(reason, []))


# --------------------------------------------------------------- the wording guard

def test_two_wordings_in_one_slot_split_the_batch(data):
    """The case the whole design turns on: same checkpoint, same index, two texts.
    The majority wording is the reference; the other one is excluded and named."""
    for name in ("Alpha", "Beta", "Gamma"):
        _session(data, _student(data, name), wording=WORDING_A)
    _session(data, _student(data, "Delta"), wording=WORDING_B)

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert plan["reference"] == WORDING_A
    assert len(plan["apply"]) == 3
    assert _skipped_names(plan, "wortlaut") == ["Kaya Delta"]
    # The excluded session's own wording is carried through, so the preview can show
    # what those students actually answered rather than just a count.
    assert plan["skipped"]["wortlaut"][0]["wording"] == WORDING_B


def test_the_minority_wording_is_never_the_reference(data):
    _session(data, _student(data, "Alpha"), wording=WORDING_B)
    for name in ("Beta", "Gamma"):
        _session(data, _student(data, name), wording=WORDING_A)

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert plan["reference"] == WORDING_A
    assert _applied_names(plan) == ["Kaya Beta", "Kaya Gamma"]


def test_a_session_without_a_snapshot_is_excluded_as_unknown(data):
    """No stored wording means no proof of which version was answered. Excluded, not
    optimistically included."""
    _session(data, _student(data, "Alpha"), wording=WORDING_A)
    attempt_id = _session(data, _student(data, "Beta"), wording=WORDING_A)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_attempt SET quiz_snapshot_json = NULL "
                     "WHERE id = ?", (attempt_id,))

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "unbekannt") == ["Kaya Beta"]


def test_without_any_stored_wording_the_batch_has_no_reference(data):
    """Then every session classifies as unknown and "matches the reference" would be
    vacuously true -- the route refuses on this."""
    attempt_id = _session(data, _student(data, "Alpha"))
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_attempt SET quiz_snapshot_json = NULL "
                     "WHERE id = ?", (attempt_id,))

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert plan["reference"] is None
    assert plan["apply"] == []


# ------------------------------------------------------------- the other exclusions

def test_a_reviewed_session_stays_out_by_default(data):
    _session(data, _student(data, "Alpha"))
    beta = _session(data, _student(data, "Beta"))
    models.set_checkpoint_teacher_review(beta, None, "", "", admin_id=1, reviewed=True)

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "geprueft") == ["Kaya Beta"]


def test_the_checkbox_lets_reviewed_sessions_back_in(data):
    beta = _session(data, _student(data, "Beta"))
    models.set_checkpoint_teacher_review(beta, None, "", "", admin_id=1, reviewed=True)

    plan = _plan(data, include_reviewed=True, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Beta"]


def test_a_hand_set_question_score_is_never_touched(data, as_admin):
    """Same rule as _double_click_corrections: never overwrite a human decision. No
    checkbox lifts this one."""
    _session(data, _student(data, "Alpha"))
    beta = _session(data, _student(data, "Beta"))
    as_admin.post(f"/admin/checkpoint-pruefung/{beta}/frage/0/punkte",
                  data={"punkte": "2"})

    plan = _plan(data, include_reviewed=True, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "von_hand") == ["Kaya Beta"]


def test_a_hand_set_session_grade_is_never_touched(data):
    """effective_checkpoint_score() lets teacher_score win, so rescoring the question
    would change the breakdown and not the grade. Listing it as changed would lie."""
    _session(data, _student(data, "Alpha"))
    beta = _session(data, _student(data, "Beta"))
    models.set_checkpoint_teacher_review(beta, 3, "meine Entscheidung", "",
                                         admin_id=1, reviewed=False)

    plan = _plan(data, include_reviewed=True, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "note_gesetzt") == ["Kaya Beta"]


def test_an_open_report_is_left_to_its_own_decision(data):
    """Setting the score here would leave the flag open, so the session stays
    provisional anyway -- the batch would look like it settled something it did not."""
    _session(data, _student(data, "Alpha"))
    beta_id = _student(data, "Beta")
    beta = _session(data, beta_id)
    models.create_checkpoint_flag(
        checkpoint_id=data["subtask_id"], question_index=0, source="student",
        student_id=beta_id, checkpoint_attempt_id=beta, reason_code="unklar")

    plan = _plan(data, include_reviewed=True, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "gemeldet") == ["Kaya Beta"]


def test_a_session_without_a_breakdown_is_excluded(data):
    """Writing one key into an empty breakdown makes the session score that one key.
    On a session that scored 3, that is a silent drop to 0."""
    _session(data, _student(data, "Alpha"))
    beta = _session(data, _student(data, "Beta"), score=3)
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_attempt SET question_scores_json = NULL "
                     "WHERE id = ?", (beta,))

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "ohne_aufschluesselung") == ["Kaya Beta"]


def test_a_reset_session_is_excluded(data):
    _session(data, _student(data, "Alpha"))
    beta = _session(data, _student(data, "Beta"))
    models.supersede_checkpoint_attempts([beta])

    plan = _plan(data, checkpoint_id=data["subtask_id"], include_superseded=True)

    assert _applied_names(plan) == ["Kaya Alpha"]
    assert _skipped_names(plan, "zurueckgesetzt") == ["Kaya Beta"]


# ------------------------------------------------------------------ the arithmetic

def test_the_preview_names_the_score_each_session_becomes(data):
    """min() over what still counts. Question 0 drops out, question 1 decides."""
    student_id = _student(data, "Alpha")
    _session(data, student_id, question_scores={"0": 0, "1": 2})

    plan = _plan(data, checkpoint_id=data["subtask_id"])
    row = plan["apply"][0]

    assert (row["old"], row["new"]) == (0, None)
    assert row["session_new"] == 2
    assert row["empties_session"] is False


def test_emptying_the_last_counting_question_is_warned_about(data):
    """The outcome that looks like mercy and is not: nothing counts -> 0, and 0 is
    exactly what the Kern-Sperre reads."""
    _session(data, _student(data, "Alpha"), question_scores={"0": 2})

    plan = _plan(data, checkpoint_id=data["subtask_id"])

    assert plan["apply"][0]["empties_session"] is True
    assert plan["apply"][0]["session_new"] == 0


# ------------------------------------------------------------------------ the route

BULK_URL = "/admin/checkpoint-pruefung/frage/{cp}/0/sammelkorrektur"


def _post(as_admin, data, **form):
    form.setdefault("punkte", "")
    return as_admin.post(BULK_URL.format(cp=data["subtask_id"]), data=form,
                         follow_redirects=True)


def test_the_first_post_only_previews(data, as_admin):
    _session(data, _student(data, "Alpha"))
    _session(data, _student(data, "Beta"), wording=WORDING_B)

    page = _post(as_admin, data, checkpoint_id=data["subtask_id"]).get_data(as_text=True)

    assert "Sammelkorrektur prüfen" in page
    assert "1 Sitzung(en) werden geändert" in page
    assert "1 Sitzung(en) bleiben unangetastet" in page
    # Nothing written yet.
    assert models.get_checkpoint_attempt(
        models.get_checkpoint_reviews()[0]["id"])["question_scores_manual_json"] is None


def test_the_confirmed_post_writes(data, as_admin):
    student_id = _student(data, "Alpha")
    attempt_id = _session(data, student_id, question_scores={"0": 0, "1": 2})

    _post(as_admin, data, checkpoint_id=data["subtask_id"], bestaetigt="1")

    attempt = models.get_checkpoint_attempt(attempt_id)
    assert json.loads(attempt["question_scores_json"])["0"] is None
    assert json.loads(attempt["question_scores_manual_json"]) == {"0": None}
    assert attempt["score"] == 2


def test_the_divergent_wording_is_still_untouched_after_the_write(data, as_admin):
    """The assertion that matters: a batch keyed on the index would have hit Beta."""
    _session(data, _student(data, "Alpha"))
    beta = _session(data, _student(data, "Beta"), wording=WORDING_B)

    _post(as_admin, data, checkpoint_id=data["subtask_id"], bestaetigt="1")

    assert models.get_checkpoint_attempt(beta)["question_scores_manual_json"] is None


def test_an_unfiltered_run_is_refused(data, as_admin):
    _session(data, _student(data, "Alpha"))

    page = _post(as_admin, data, bestaetigt="1").get_data(as_text=True)

    assert "zuerst nach Klasse, Schüler oder Checkpoint filtern" in page
    assert models.get_checkpoint_attempt(
        models.get_checkpoint_reviews()[0]["id"])["question_scores_manual_json"] is None


def test_a_score_that_could_lower_a_three_is_refused(data, as_admin):
    """3.5: „zählt nicht" only. A fixed 2 would drop everyone who scored 3, and that
    value waits until the preview has been used in anger."""
    _session(data, _student(data, "Alpha"))

    page = _post(as_admin, data, checkpoint_id=data["subtask_id"], punkte="2",
                 bestaetigt="1").get_data(as_text=True)

    assert "bisher nur „zählt nicht" in page
    assert models.get_checkpoint_attempt(
        models.get_checkpoint_reviews()[0]["id"])["question_scores_manual_json"] is None


def test_the_write_warns_when_a_session_ends_up_empty(data, as_admin):
    _session(data, _student(data, "Alpha"), question_scores={"0": 2})

    page = _post(as_admin, data, checkpoint_id=data["subtask_id"],
                 bestaetigt="1").get_data(as_text=True)

    assert "Kern-Sperre bleibt zu" in page



def test_the_preview_offers_the_confirm_button_with_its_count(data, as_admin):
    for name in ("Alpha", "Beta"):
        _session(data, _student(data, name))

    page = _post(as_admin, data, checkpoint_id=data["subtask_id"]).get_data(as_text=True)

    assert "Ja, 2 Sitzung(en) so ändern" in page
    assert 'name="bestaetigt"' in page


def test_the_scope_toggle_reloads_the_preview_instead_of_writing(data, as_admin):
    """Two plain forms rather than a self-submitting checkbox: the toggle posts
    without `bestaetigt`, so it can only ever land back on a preview."""
    beta = _session(data, _student(data, "Beta"))
    models.set_checkpoint_teacher_review(beta, None, "", "", admin_id=1, reviewed=True)

    default = _post(as_admin, data,
                    checkpoint_id=data["subtask_id"]).get_data(as_text=True)
    widened = _post(as_admin, data, checkpoint_id=data["subtask_id"],
                    auch_geprueft="1").get_data(as_text=True)

    assert "Keine Sitzung erfüllt die Bedingungen." in default
    assert "Ja, 1 Sitzung(en) so ändern" in widened
    # Neither is a write.
    assert models.get_checkpoint_attempt(beta)["question_scores_manual_json"] is None
