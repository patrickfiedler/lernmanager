"""Regression tests for the Chemie Quiz-checkpoint retry-session flow
(_handle_checkpoint_quiz + /schueler/checkpoint/* routes in app.py).
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Was ist die Oxidationszahl von Cl in Cl2?", "options": ["0", "+1", "-1"], "correct": [0]},
    ]
}
QUIZ_MULTI = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage 2", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}
HINTS = ["Denk an die Elektronegativitaet.", "Gleiche Atome teilen sich Elektronen gleich."]


def _checkpoint_student(app, quiz=QUIZ):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "checkpointtest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Redoxreaktionen", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Oxidationszahlen", reihenfolge=0,
        quiz_json=json.dumps(quiz), checkpoint_type="quiz", kern_standard_tag="kern",
        checkpoint_hints_json=json.dumps(HINTS),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_checkpoint_page_renders_question_not_answer(app, client):
    student_id, _ = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.get("/schueler/thema/redoxreaktionen/aufgabe-1/quiz")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Oxidationszahl von Cl" in body


def test_wrong_answer_does_not_reveal_correct_and_allows_retry(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    wrong = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })
    data = wrong.get_json()
    assert data["correct"] is False
    assert "correct_answer" not in data
    assert data["attempts"] == 1

    right = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    data = right.get_json()
    assert data["correct"] is True
    assert data["attempts"] == 2


def test_hint_gated_until_after_first_attempt(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    too_early = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert too_early.status_code == 403

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })

    first_hint = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert first_hint.get_json()["hint"] == HINTS[0]

    second_hint = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert second_hint.get_json()["hint"] == HINTS[1]

    no_more = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert no_more.get_json()["hint"] is None


def test_give_up_reveals_correct_answer(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    assert resp.get_json()["correct_answer"] == "0"


def test_finish_rejects_unresolved_checkpoint(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert resp.status_code == 400


def test_finish_scores_3_on_clean_first_try(app, client):
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert resp.status_code == 200
    assert resp.get_json()["score"] == 3

    attempts = models.get_checkpoint_attempts_for_student(student_id)
    assert attempts[0]["score"] == 3


def test_finish_scores_worst_case_across_questions(app, client):
    """Per chemie-data-contract.md §3a: consolidation is min(), not average -
    one question solved via hint (2) and one given up (0) -> checkpoint = 0."""
    student_id, subtask_id = _checkpoint_student(app, quiz=QUIZ_MULTI)
    _login(client, student_id)

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })
    client.post("/schueler/checkpoint/hinweis", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0
    })
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    client.post("/schueler/checkpoint/aufgeben", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 1
    })

    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert resp.status_code == 200
    assert resp.get_json()["score"] == 0


def test_answers_are_logged_per_attempt_and_backfilled_on_finish(app, client):
    """migrate_047: checkpoint_answer must capture every submitted attempt (not
    just the final one) with the real answer text, then get stamped with the
    checkpoint_attempt_id once the session finishes."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [1]
    })
    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })

    with models.db_session() as conn:
        unstamped = conn.execute(
            "SELECT COUNT(*) FROM checkpoint_answer WHERE student_id = ? AND checkpoint_attempt_id IS NULL",
            (student_id,)
        ).fetchone()[0]
    assert unstamped == 2  # both attempts logged, not stamped yet (no checkpoint_attempt exists until /fertig)

    resp = client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    attempt_id = models.get_checkpoint_attempts_for_student(student_id)[0]["id"]

    logged = models.get_checkpoint_answers_for_attempt(attempt_id)
    assert len(logged) == 2
    assert logged[0]["attempt_no"] == 1 and logged[0]["correct"] == 0
    assert json.loads(logged[0]["answer_text"]) == [1]
    assert logged[1]["attempt_no"] == 2 and logged[1]["correct"] == 1
    assert json.loads(logged[1]["answer_text"]) == [0]


def test_reset_supersedes_checkpoint_attempt_instead_of_deleting(app, client):
    """The teacher's explicit call (2026-08-25): a content re-import with
    'Fortschritte zuruecksetzen' must not erase graded checkpoint history --
    soft-delete via superseded_at, and the gate must ignore superseded rows."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    with models.db_session() as conn:
        task_id = conn.execute(
            "SELECT task_id FROM subtask WHERE id = ?", (subtask_id,)
        ).fetchone()["task_id"]
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)
        ).fetchone()["id"]

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    assert models.has_passed_subtask_quiz(student_task_id, subtask_id) is True

    models.reset_student_progress_for_task(task_id)

    # Row survives (superseded, not deleted) -- excluded from the default query...
    assert models.get_checkpoint_attempts_for_student(student_id) == []
    # ...but still readable as history, and the answer log is untouched either way.
    all_attempts = models.get_checkpoint_attempts_for_student(student_id, include_superseded=True)
    assert len(all_attempts) == 1
    assert all_attempts[0]["superseded_at"] is not None
    assert len(models.get_checkpoint_answers_for_attempt(all_attempts[0]["id"])) == 1

    # And the progression gate correctly forgets the pre-reset pass (commit f9d6a24's fix).
    assert models.has_passed_subtask_quiz(student_task_id, subtask_id) is False


def test_deleting_subtask_does_not_cascade_delete_checkpoint_history(app, client):
    """migrate_047: checkpoint_id carries no FK/cascade, so editing away an
    Aufgabe must not silently wipe students' logged scores/answers for it."""
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id, "question_index": 0, "answer": [0]
    })
    client.post("/schueler/checkpoint/fertig", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id
    })
    attempt_id = models.get_checkpoint_attempts_for_student(student_id)[0]["id"]

    with models.db_session() as conn:
        conn.execute("DELETE FROM subtask WHERE id = ?", (subtask_id,))

    attempts = models.get_checkpoint_attempts_for_student(student_id)
    assert len(attempts) == 1
    assert attempts[0]["quiz_snapshot_json"] is not None
    assert len(models.get_checkpoint_answers_for_attempt(attempt_id)) == 1


def test_resubmitting_a_solved_question_does_not_burn_an_attempt(app, client):
    """The double-click damage case: a second submission of an already-solved
    question must not count as a second attempt.

    3 points requires attempts == 1 (_checkpoint_question_scores), so before the
    guard in student_checkpoint_answer a stray second click silently turned a 3
    into a 2 -- and spent an LLM call doing it.
    """
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    payload = {"slug": "redoxreaktionen", "subtask_id": subtask_id,
               "question_index": 0, "answer": [0]}
    first = client.post("/schueler/checkpoint/antwort", json=payload).get_json()
    second = client.post("/schueler/checkpoint/antwort", json=payload).get_json()

    assert first["correct"] is True
    assert first["attempts"] == 1
    assert second["correct"] is True
    assert second["attempts"] == 1          # unchanged
    assert second["duplicate"] is True

    client.post("/schueler/checkpoint/fertig",
                json={"slug": "redoxreaktionen", "subtask_id": subtask_id})
    attempt = models.get_checkpoint_attempts_for_student(student_id)[0]
    assert attempt["score"] == 3


QUIZ_SHORT = {
    "questions": [
        {"type": "short_answer", "text": "Erklaere, warum Cl2 die Oxidationszahl 0 hat.",
         "rubric": "Gleiche Atome, gleiche Elektronegativitaet, Bindungselektronen werden geteilt."},
    ]
}

# What a lenient grader writes back: a sentence naming exactly what the answer was
# missing. Fine for practice, a giveaway in a graded checkpoint.
LEAKY_FEEDBACK = "Fast richtig -- es fehlt der Hinweis auf die gleiche Elektronegativitaet."


def test_checkpoint_answer_response_carries_no_llm_feedback(app, client, monkeypatch):
    """The LLM's feedback sentence is written for the teacher, never for the student.

    Checkpoint grading deliberately uses a stricter prompt, but that prompt still
    produces a one-sentence explanation -- and in a retry-until-correct session
    "here is what your answer was missing" hands over the answer. The sentence is
    logged to checkpoint_answer (the teacher review page reads it) and dropped from
    the HTTP response. This test pins the drop: student_checkpoint_answer must
    return the verdict and the attempt count, nothing else.
    """
    import llm_grading

    monkeypatch.setattr(llm_grading, "grade_answer", lambda *a, **kw: {
        "correct": False, "feedback": LEAKY_FEEDBACK,
        "source": "llm", "prompt_version": "checkpoint:testhash",
    })

    student_id, subtask_id = _checkpoint_student(app, quiz=QUIZ_SHORT)
    _login(client, student_id)

    resp = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": 0, "answer": "Weil es ein Element ist.",
    })

    assert set(resp.get_json()) == {"correct", "attempts"}
    assert "Elektronegativitaet" not in resp.get_data(as_text=True)

    # ... but it was produced and kept -- this is a transport-level rule, not the
    # absence of feedback. If this half fails the test above passes for the wrong
    # reason (nothing was graded at all).
    with models.db_session() as conn:
        logged = conn.execute(
            "SELECT feedback FROM checkpoint_answer WHERE checkpoint_id = ?", (subtask_id,)
        ).fetchone()
    assert logged["feedback"] == LEAKY_FEEDBACK


def test_wrong_multiple_choice_response_carries_no_option_text(app, client):
    """The MC branch of _grade_warmup_answer builds "Richtig war: ..." feedback for
    warmup, where revealing the answer is the point. Same helper, same checkpoint
    route -- so the option text must not ride along in the response either.
    """
    student_id, subtask_id = _checkpoint_student(app)
    _login(client, student_id)

    resp = client.post("/schueler/checkpoint/antwort", json={
        "slug": "redoxreaktionen", "subtask_id": subtask_id,
        "question_index": 0, "answer": [2],
    })

    body = resp.get_data(as_text=True)
    assert set(resp.get_json()) == {"correct", "attempts"}
    assert "Richtig war" not in body
