"""End-to-end coverage for the ordering/matching question types across the
three surfaces that grade them: the quiz form, the warm-up, and the checkpoint.

The recurring risk in all three is the same one the fill_blank/MC paths already
carry: the payload that renders a question must not contain what grades it.
"""
import json

import models
import quiz_grading
from app import _serialize_question_for_js, _serialize_checkpoint_question
from import_task import _validate_quiz


QUIZ = {
    "questions": [
        {"type": "ordering", "text": "Reihenfolge?",
         "items": ["Eins", "Zwei", "Drei", "Vier"]},
        {"type": "matching", "text": "Zuordnung?",
         "pairs": [["Anode", "Oxidation"], ["Kathode", "Reduktion"]],
         "distractors": ["Neutralisation"]},
    ]
}


def _attempt(student_id, klasse_id):
    """The newest quiz_attempt for this student, read straight from the table --
    the topic auto-completes on a passing attempt, so the "active topic"
    accessors no longer find it."""
    with models.db_session() as conn:
        row = conn.execute(
            "SELECT qa.* FROM quiz_attempt qa JOIN student_task st ON qa.student_task_id = st.id"
            " WHERE st.student_id = ? ORDER BY qa.id DESC LIMIT 1", (student_id,)).fetchone()
    return dict(row)


def _student_with_quiz_topic(app, quiz=None):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "ordtest", "pw123",
                                       lernpfad="bergweg")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht",
                                 quiz_json=json.dumps(quiz or QUIZ))
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, klasse_id


# --- the quiz form ----------------------------------------------------------

def test_quiz_form_renders_the_pieces_without_the_answer_key(app, client):
    student_id, klasse_id = _student_with_quiz_topic(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    body = client.get("/schueler/thema/testthema/quiz").get_data(as_text=True)

    assert "qi-container" in body
    assert "Neutralisation" in body          # distractor is offered
    # The authored order must not survive into the page as authored -- that is
    # the answer to the ordering question.
    assert "Eins&quot;, &quot;Zwei&quot;, &quot;Drei&quot;, &quot;Vier" not in body


def test_quiz_form_awards_a_half_point_for_a_partly_right_answer(app, client):
    student_id, klasse_id = _student_with_quiz_topic(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0, 1]),
        "q0": json.dumps(["Eins", "Zwei", "Drei", "Vier"]),        # fully right
        "q1": json.dumps({"Anode": "Oxidation",
                          "Kathode": "Neutralisation"}),           # 1 of 2
    }, follow_redirects=True)
    assert resp.status_code == 200

    attempt = _attempt(student_id, klasse_id)
    # 1.0 for the ordering question + floor(1 of 2 pairs) = 0.5
    assert attempt["punkte"] == 1.5
    assert attempt["max_punkte"] == 2


def test_quiz_form_stores_a_readable_answer_for_the_result_page(app, client):
    student_id, klasse_id = _student_with_quiz_topic(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0, 1]),
        "q0": json.dumps(["Zwei", "Eins", "Drei", "Vier"]),
        "q1": json.dumps({"Anode": "Oxidation", "Kathode": "Reduktion"}),
    }, follow_redirects=True)

    antworten = json.loads(_attempt(student_id, klasse_id)["antworten_json"])
    assert antworten["0"]["text"] == "Zwei → Eins → Drei → Vier"
    assert antworten["0"]["correct"] is False
    assert antworten["1"]["correct"] is True
    assert antworten["1"]["source"] == "interactive"


def test_result_page_reveals_the_solution_only_for_a_wrong_answer(app, client):
    student_id, klasse_id = _student_with_quiz_topic(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    body = client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0, 1]),
        "q0": json.dumps(["Vier", "Drei", "Zwei", "Eins"]),
        "q1": json.dumps({"Anode": "Oxidation", "Kathode": "Reduktion"}),
    }, follow_redirects=True).get_data(as_text=True)

    # One solution block only: the ordering question, which was wrong. The
    # matching answer was right, so nothing extra is revealed for it.
    assert "Eins → Zwei → Drei → Vier" in body
    assert body.count("Richtig wäre:") == 1


def test_a_missing_field_scores_zero_rather_than_erroring(app, client):
    student_id, klasse_id = _student_with_quiz_topic(app)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    resp = client.post("/schueler/thema/testthema/quiz", data={
        "question_order": json.dumps([0, 1]),
    }, follow_redirects=True)
    assert resp.status_code == 200

    assert _attempt(student_id, klasse_id)["punkte"] == 0


# --- warm-up / practice -----------------------------------------------------

def _pool_item(question):
    return {"task_id": 1, "subtask_id": None, "question_index": 0,
            "topic_name": "Testthema", "question": question}


def test_warmup_payload_carries_no_ordering_answer_key():
    result = _serialize_question_for_js(_pool_item(QUIZ["questions"][0]))
    assert sorted(result["items"]) == ["Drei", "Eins", "Vier", "Zwei"]
    assert result["items"] != QUIZ["questions"][0]["items"]
    assert "correct" not in result


def test_warmup_payload_carries_no_matching_answer_key():
    result = _serialize_question_for_js(_pool_item(QUIZ["questions"][1]))
    assert "pairs" not in result
    assert "distractors" not in result
    assert sorted(result["left"]) == ["Anode", "Kathode"]
    assert sorted(result["right"]) == ["Neutralisation", "Oxidation", "Reduktion"]


def test_checkpoint_payload_carries_no_answer_key():
    result = _serialize_checkpoint_question(QUIZ["questions"][1], 1)
    assert "pairs" not in result and "distractors" not in result
    # The exact key set is pinned on purpose: a new key has to be admitted here
    # deliberately, so an answer-carrying field cannot slip into the payload.
    assert set(result) == {"type", "text", "left", "right", "index"}
    assert result["index"] == 1


def test_interactive_types_stay_in_the_warmup_pool():
    entries = models._quiz_json_to_pool_entries(
        1, None, json.dumps(QUIZ), "Testthema")
    assert [e["question"]["type"] for e in entries] == ["ordering", "matching"]


def test_editing_the_pairs_changes_the_question_hash():
    # Stats bucket by hash; the pairs are what "the correct answer" means here,
    # so an edited question must not silently inherit the old question's stats.
    before = models._question_hash(QUIZ["questions"][1])
    edited = json.loads(json.dumps(QUIZ["questions"][1]))
    edited["pairs"][0][1] = "Reduktion"
    assert models._question_hash(edited) != before


# --- import validation ------------------------------------------------------

def test_import_rejects_duplicate_ordering_items():
    errors = _validate_quiz({"questions": [
        {"type": "ordering", "text": "x", "items": ["A", "B", "A"]}]})
    assert errors and "duplicate" in errors[0]


def test_import_rejects_a_distractor_that_repeats_a_right_hand_entry():
    errors = _validate_quiz({"questions": [
        {"type": "matching", "text": "x", "pairs": [["A", "1"], ["B", "2"]],
         "distractors": ["1"]}]})
    assert errors and "right column" in errors[0]


def test_import_rejects_a_malformed_pair():
    errors = _validate_quiz({"questions": [
        {"type": "matching", "text": "x", "pairs": [["A", "1"], ["B"]]}]})
    assert errors and "links, rechts" in errors[0]


def test_import_accepts_a_well_formed_pair_of_questions():
    assert _validate_quiz(QUIZ) == []
