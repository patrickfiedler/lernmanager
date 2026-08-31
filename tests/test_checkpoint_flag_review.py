"""The teacher's side of a reported checkpoint question
(/admin/checkpoint-pruefung + /admin/checkpoint-pruefung/meldung/<id>/urteil).

A report is a claim about the QUESTION, so it gets its own badge and its own
filter -- never needs_review, which means "LLM grading was unavailable".
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage 2", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}


def _finished_session_with_report(app, client, reason="unklar", reason_text=None):
    """One completed checkpoint: question 1 reported, question 2 answered cleanly."""
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "flagreview", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(QUIZ), checkpoint_type="quiz", kern_standard_tag="kern",
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    client.post("/schueler/checkpoint/melden", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0,
        "reason_code": reason, "reason_text": reason_text,
    })
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 1, "answer": [0]
    })
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    with client.session_transaction() as sess:
        sess.pop("student_id", None)
    return student_id, subtask_id


def test_review_page_shows_the_report_and_its_reason(app, client, as_admin):
    _finished_session_with_report(app, client, reason="nicht_behandelt",
                                  reason_text="Das hatten wir nie")

    body = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "Das hatten wir noch nicht" in body      # the preset's label
    assert "Das hatten wir nie" in body             # the student's own words
    assert "gemeldet" in body


def test_the_reported_question_shows_no_score_yet(app, client, as_admin):
    _finished_session_with_report(app, client)

    body = as_admin.get("/admin/checkpoint-pruefung").get_data(as_text=True)
    assert "— P." in body


def test_the_flagged_filter_is_its_own_filter(app, client, as_admin):
    _finished_session_with_report(app, client)

    listed = models.get_checkpoint_reviews(flagged_only=True)
    assert len(listed) == 1

    # ... and it is not needs_review: the LLM worked fine here.
    assert listed[0]["needs_review"] == 0
    assert models.get_checkpoint_reviews(unreviewed_only=True, flagged_only=True)


def test_a_verdict_closes_the_report(app, client, as_admin):
    _finished_session_with_report(app, client)
    flag = models.get_checkpoint_flags()[0]

    resp = as_admin.post(f"/admin/checkpoint-pruefung/meldung/{flag['id']}/urteil",
                         data={"status": "frage_kaputt", "resolution_note": "Bild fehlte"})
    assert resp.status_code == 302

    updated = models.get_checkpoint_flags()[0]
    assert updated["status"] == "frage_kaputt"
    assert updated["resolution_note"] == "Bild fehlte"
    assert updated["resolved_at"] is not None
    # Closed reports drop out of the filter -- there is nothing left to decide.
    assert models.get_checkpoint_reviews(flagged_only=True) == []


def test_an_unknown_verdict_changes_nothing(app, client, as_admin):
    _finished_session_with_report(app, client)
    flag = models.get_checkpoint_flags()[0]

    as_admin.post(f"/admin/checkpoint-pruefung/meldung/{flag['id']}/urteil",
                  data={"status": "egal"})

    assert models.get_checkpoint_flags()[0]["status"] == "offen"


def test_a_rejected_report_still_counts_as_undecided(app, client, as_admin):
    """'abgelehnt' is not the end: the student still owes that question, so the
    session score stays provisional until they have redone it."""
    student_id, subtask_id = _finished_session_with_report(app, client)
    flag = models.get_checkpoint_flags()[0]

    as_admin.post(f"/admin/checkpoint-pruefung/meldung/{flag['id']}/urteil",
                  data={"status": "abgelehnt"})

    attempt = models.get_latest_checkpoint_attempt(student_id, subtask_id)
    assert models.checkpoint_score_is_provisional(attempt) is True


def test_a_question_reported_by_several_students_is_counted(app, client, as_admin):
    _finished_session_with_report(app, client)
    counts = models.count_open_flags_by_question(
        [models.get_checkpoint_flags()[0]["checkpoint_id"]]
    )
    assert list(counts.values()) == [1]
