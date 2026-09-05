"""Repairing a single checkpoint question from the admin review page.

Patrick, 2026-09-01: the page could only ask "War die KI-Bewertung richtig?" --
a judgement about one grading decision that never moves a score. Missing was the
other claim, "this QUESTION is at fault", and the two repairs that follow from it:
send the one question back to the student, or set its score by hand. Chemie's
grading works per question, so both have to reach a question and not a whole
checkpoint.
"""
import json
import re

import models


def _csrf(client):
    resp = client.get("/admin")
    return re.search(r'name="csrf-token" content="([^"]+)"',
                     resp.get_data(as_text=True)).group(1)


def _post(client, url, **data):
    data["csrf_token"] = _csrf(client)
    return client.post(url, data=data)


QUIZ = {
    "questions": [
        {"text": "Frage eins", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage zwei", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage drei", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}


def _attempt(scores=None, score=2):
    """One finished session with a stored per-question breakdown."""
    student_id = models.create_student("Test", "Schueler", "repairtest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    attempt_id = models.create_checkpoint_attempt(
        student_id, checkpoint_id=subtask_id, module_id=task_id, checkpoint_type="quiz",
        kern_standard_tag="kern", score=score,
        quiz_snapshot_json=json.dumps(QUIZ),
        question_scores_json=json.dumps(scores if scores is not None
                                        else {"0": 3, "1": 2, "2": 3}))
    return student_id, subtask_id, attempt_id


def _flags(**kw):
    return models.get_checkpoint_flags(**kw)


# --- the verdict vocabulary -------------------------------------------------

def test_teacher_verdicts_exclude_abgelehnt():
    """A teacher flagging a question on their own has no report to reject, so
    offering 'abgelehnt' would be a button that cannot mean anything."""
    assert "design_fehlerhaft" in models.CHECKPOINT_FLAG_TEACHER_VERDICTS
    assert "frage_kaputt" in models.CHECKPOINT_FLAG_TEACHER_VERDICTS
    assert "abgelehnt" not in models.CHECKPOINT_FLAG_TEACHER_VERDICTS
    # ...but it stays available when ruling on a student's report.
    assert "abgelehnt" in models.CHECKPOINT_FLAG_RESOLUTIONS
    assert "design_fehlerhaft" in models.CHECKPOINT_FLAG_RESOLUTIONS


def test_every_resolution_has_a_flash_line(as_admin):
    """The route used to look its message up in an exhaustive dict -- a verdict
    added to the vocabulary without a line there raised KeyError at click time."""
    import app as app_module
    assert set(models.CHECKPOINT_FLAG_RESOLUTIONS) <= set(app_module._FLAG_VERDICT_FLASH)


# --- flagging the question --------------------------------------------------

def test_teacher_flag_is_about_the_question_not_a_student(as_admin):
    _student_id, subtask_id, _attempt_id = _attempt()
    resp = _post(as_admin, f"/admin/checkpoint-pruefung/frage/{subtask_id}/1/markieren", status="design_fehlerhaft",
                               reason_text="Die Aufgabe erklärt das nicht")
    assert resp.status_code == 302

    flag = _flags(checkpoint_id=subtask_id, question_index=1)[0]
    assert flag["source"] == "teacher"
    assert flag["student_id"] is None          # a claim about the question, about nobody
    assert flag["status"] == "design_fehlerhaft"   # the verdict is immediate, not 'offen'
    assert flag["reason_text"] == "Die Aufgabe erklärt das nicht"
    assert flag["question_text_at_flag"] == "Frage zwei"   # pinned before the rewrite


def test_teacher_flag_alone_changes_no_score(as_admin):
    """The decisive difference to a confirmed student report: this must not
    silently rewrite the grade of a session that was finished weeks ago."""
    _student_id, subtask_id, attempt_id = _attempt(score=2)
    _post(as_admin, f"/admin/checkpoint-pruefung/frage/{subtask_id}/1/markieren", status="frage_kaputt")
    assert models.get_checkpoint_attempt(attempt_id)["score"] == 2


def test_unknown_verdict_is_refused(as_admin):
    _student_id, subtask_id, _attempt_id = _attempt()
    _post(as_admin, f"/admin/checkpoint-pruefung/frage/{subtask_id}/0/markieren", status="gefaellt_mir_nicht")
    assert _flags(checkpoint_id=subtask_id) == []


# --- repair 1: send one question back ---------------------------------------

def test_retry_sends_back_exactly_one_question(as_admin):
    student_id, subtask_id, attempt_id = _attempt()
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/2/nachbessern")

    owed = models.get_flags_for_retry(student_id, subtask_id)
    assert [f["question_index"] for f in owed] == [2]
    assert owed[0]["status"] == "nachbesserung"
    assert owed[0]["source"] == "teacher"


def test_retry_is_not_offered_twice(as_admin):
    student_id, subtask_id, attempt_id = _attempt()
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/2/nachbessern")
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/2/nachbessern")
    assert len(models.get_flags_for_retry(student_id, subtask_id)) == 1


def test_retry_refused_on_a_reset_session(as_admin):
    """A reset already hands the whole checkpoint back; one question on top of
    that would leave a flag nothing ever closes."""
    student_id, subtask_id, attempt_id = _attempt()
    models.supersede_checkpoint_attempts([attempt_id])
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/2/nachbessern")
    assert models.get_flags_for_retry(student_id, subtask_id) == []


def test_redo_of_a_teacher_flag_is_not_capped(as_admin):
    """REJECTED_FLAG_RETRY_CAP exists because a student reported a working
    question. Here the fault is ours, so a clean redo can still score 3 -- while
    a rejected report in the same sitting stays capped."""
    from app import _checkpoint_question_scores
    results = [
        {"index": 0, "solved": True, "gave_up": False, "flagged": False,
         "attempts": 1, "hints_used": 0, "retry_after_rejected_flag": False},
        {"index": 1, "solved": True, "gave_up": False, "flagged": False,
         "attempts": 1, "hints_used": 0, "retry_after_rejected_flag": True},
    ]
    assert _checkpoint_question_scores(results) == [3, 2]


def test_redo_closes_a_teacher_flag_too(as_admin):
    student_id, subtask_id, attempt_id = _attempt()
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/2/nachbessern")
    flag_id = models.get_flags_for_retry(student_id, subtask_id)[0]["id"]

    models.mark_checkpoint_flags_retried([flag_id])
    assert models.get_flags_for_retry(student_id, subtask_id) == []
    assert _flags(checkpoint_id=subtask_id, question_index=2)[0]["status"] == "nachgeholt"


# --- repair 2: set one question's score by hand -----------------------------

def test_hand_set_score_rewrites_only_that_question(as_admin):
    _student_id, _subtask_id, attempt_id = _attempt(scores={"0": 3, "1": 0, "2": 3},
                                                    score=0)
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/1/punkte", punkte="3")

    attempt = models.get_checkpoint_attempt(attempt_id)
    assert json.loads(attempt["question_scores_json"]) == {"0": 3, "1": 3, "2": 3}
    assert attempt["score"] == 3          # min() over the questions that count
    # Provenance: without this the correction is invisible on the next visit.
    assert json.loads(attempt["question_scores_manual_json"]) == {"1": 3}


def test_zaehlt_nicht_takes_the_question_out_of_the_min(as_admin):
    _student_id, _subtask_id, attempt_id = _attempt(scores={"0": 3, "1": 0, "2": 3},
                                                    score=0)
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/1/punkte", punkte="")

    attempt = models.get_checkpoint_attempt(attempt_id)
    assert json.loads(attempt["question_scores_json"])["1"] is None
    assert attempt["score"] == 3


def test_a_session_where_nothing_counts_is_zero(as_admin):
    """0, not None: the Kern-Sperre reads a number and nothing else, so the floor
    has to be a number. Voiding a whole session is the session-level override."""
    _student_id, _subtask_id, attempt_id = _attempt(scores={"0": 3}, score=3)
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/0/punkte", punkte="")
    assert models.get_checkpoint_attempt(attempt_id)["score"] == 0


def test_legacy_vorher_key_still_counts(as_admin):
    """An attempt from before per-question scores stores {'vorher': score} as a
    floor. Dropping it would let one hand-set 3 lift a session above what it earned."""
    from app import _consolidate_question_scores
    assert _consolidate_question_scores({"vorher": 0, "1": 3}) == 0
    assert _consolidate_question_scores({"vorher": 3, "1": 2}) == 2


def test_invalid_score_is_refused(as_admin):
    _student_id, _subtask_id, attempt_id = _attempt(scores={"0": 3}, score=3)
    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/0/punkte", punkte="1")
    assert models.get_checkpoint_attempt(attempt_id)["score"] == 3


# --- the page itself --------------------------------------------------------

def _session_with_answers():
    """A session that actually renders: _build_checkpoint_sessions groups the
    ANSWER log, so an attempt without answers shows no questions at all."""
    student_id, subtask_id, attempt_id = _attempt(scores={"0": 3, "1": 0, "2": 3},
                                                  score=0)
    for index, correct in enumerate([True, False, True]):
        models.create_checkpoint_answer(
            student_id, checkpoint_id=subtask_id, session_uid="uid-render",
            question_index=index, attempt_no=1, answer_text="[0]",
            correct=correct, feedback=None, grader="mc")
    with models.db_session() as conn:
        conn.execute("UPDATE checkpoint_answer SET checkpoint_attempt_id = ? "
                     "WHERE session_uid = 'uid-render'", (attempt_id,))
    return student_id, subtask_id, attempt_id


def test_the_session_view_renders_the_two_per_student_repairs(as_admin):
    """The controls are separate forms in a template that already carries several
    others -- a rendering test is the only thing that sees them arrive."""
    _student_id, _subtask_id, attempt_id = _session_with_answers()
    html = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert f"/admin/checkpoint-pruefung/{attempt_id}/frage/0/nachbessern" in html
    assert f"/admin/checkpoint-pruefung/{attempt_id}/frage/0/punkte" in html


def test_the_class_wide_flag_form_left_the_session_view(as_admin):
    """B3: „Frage bemängeln" is one statement about the question for the whole class,
    and the session view rendered a copy of it per student per question. It lives in
    the Fragen tab now; the session view only points at it."""
    _student_id, subtask_id, _attempt_id = _session_with_answers()
    html = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert f"/admin/checkpoint-pruefung/frage/{subtask_id}/0/markieren" not in html
    assert "ansicht=fragen" in html      # the pointer that replaced it


def test_the_flag_form_renders_once_per_question_in_the_question_view(as_admin):
    """Once per question, not once per session that contained it -- that duplication
    is the whole reason the control moved."""
    _student_id, subtask_id, _attempt_id = _session_with_answers()
    html = as_admin.get(
        "/admin/checkpoint-pruefung?ansicht=fragen").get_data(as_text=True)

    action = f"/admin/checkpoint-pruefung/frage/{subtask_id}/0/markieren"
    assert html.count(action) == 1
    assert "Frage bemängeln" in html
    # All three content verdicts offered, 'abgelehnt' not among them.
    assert "Frage ist kaputt" in html
    assert "die Aufgabe bereitet nicht darauf vor" in html


def test_every_new_form_carries_a_csrf_token(as_admin):
    """Caught in review: all three forms shipped without one first, which CSRF
    protection turns into a generic error flash rather than a visible failure."""
    _session_with_answers()
    sessions = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    questions = as_admin.get(
        "/admin/checkpoint-pruefung?ansicht=fragen").get_data(as_text=True)
    forms = re.findall(r"<form[^>]*>.*?</form>", sessions + questions, re.DOTALL)
    new_forms = [f for f in forms
                 if "/markieren" in f or "/nachbessern" in f or "/punkte" in f]
    assert len(new_forms) == 9   # 2 per-student repairs x 3 questions + 3 flag forms
    assert all('name="csrf_token"' in f for f in new_forms)


def test_hand_set_score_is_marked_as_such_on_the_page(as_admin):
    """A corrected score must not read like a computed one -- the whole reason
    question_scores_manual_json exists (migrate_056)."""
    _student_id, _subtask_id, attempt_id = _session_with_answers()
    # The badge, not the words -- "Punkte von Hand:" is the control's own label.
    badge = "✋ von Hand"
    html = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert badge not in html
    assert "0 P." in html          # question 1 as the answer log has it

    _post(as_admin, f"/admin/checkpoint-pruefung/{attempt_id}/frage/1/punkte", punkte="3")
    html = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert badge in html
    # ...and the corrected value replaces the one derived from the answer log.
    assert "0 P." not in html


# --- the whole way through --------------------------------------------------

def _finished_session(app, client):
    """A normal, fully solved sitting -- nothing reported by anyone."""
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "e2etest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern")
    models.assign_task_to_student(student_id, klasse_id, task_id)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    for index in range(3):
        client.post("/schueler/checkpoint/antwort", json={
            "slug": "redoxreaktionen", "subtask_id": subtask_id,
            "question_index": index, "answer": [0]})
    client.post("/schueler/checkpoint/fertig",
                json={"slug": "redoxreaktionen", "subtask_id": subtask_id})
    return student_id, subtask_id


def test_a_returned_question_runs_the_whole_way_and_is_not_capped(app, client):
    """The end-to-end case the unit tests cannot see: teacher sends one question
    back, the student gets only that one, and a clean redo still scores 3 --
    unlike a redo after a rejected report, which is capped at 2."""
    student_id, subtask_id = _finished_session(app, client)
    attempt_id = models.get_latest_checkpoint_attempt(student_id, subtask_id)["id"]

    with client.session_transaction() as sess:
        sess["admin_id"] = models.create_admin("repairadmin", "pw")
        sess.pop("student_id", None)
    client.post(f"/admin/checkpoint-pruefung/{attempt_id}/frage/1/nachbessern",
                data={"reason_text": "Formel war falsch gesetzt"})

    with client.session_transaction() as sess:
        sess.pop("admin_id", None)
        sess["student_id"] = student_id

    body = client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz").get_data(as_text=True)
    assert "Frage zwei" in body
    assert "Frage eins" not in body        # only the returned question is asked again

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": 1, "answer": [0]})
    finish = client.post("/schueler/checkpoint/fertig",
                         json={"slug": "redoxreaktionen", "subtask_id": subtask_id}).get_json()

    assert finish["score"] == 3            # NOT capped at REJECTED_FLAG_RETRY_CAP
    attempts = models.get_checkpoint_attempts_for_student(student_id)
    assert len(attempts) == 1              # rescored, not a second sitting
    assert json.loads(attempts[0]["question_scores_json"]) == {"0": 3, "1": 3, "2": 3}
    assert models.get_checkpoint_flags()[0]["status"] == "nachgeholt"


def test_an_open_return_keeps_the_score_provisional(app, client):
    """Same rule as an open report: a question the student still owes means
    `score >= 2` does not yet prove every question was solved."""
    student_id, subtask_id = _finished_session(app, client)
    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    assert models.checkpoint_score_is_provisional(attempt) is False

    with client.session_transaction() as sess:
        sess["admin_id"] = models.create_admin("repairadmin2", "pw")
    client.post(f"/admin/checkpoint-pruefung/{attempt['id']}/frage/1/nachbessern")

    assert models.checkpoint_score_is_provisional(attempt) is True


def test_a_question_level_mark_stays_visible_on_the_page(as_admin):
    """It belongs to no sitting, so it is not in the per-attempt grouping. Without
    the merge the teacher marks a question, reloads, and sees nothing."""
    _student_id, subtask_id, _attempt_id = _session_with_answers()
    _post(as_admin, f"/admin/checkpoint-pruefung/frage/{subtask_id}/1/markieren",
          status="design_fehlerhaft", reason_text="Aufgabe 3 erklärt das nicht")

    html = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Von dir markiert" in html
    assert "Aufgabe 3 erklärt das nicht" in html
    # ...and it reads as the teacher's own claim, not as a student report.
    assert "⚠️ Gemeldet: design_fehlerhaft" not in html
