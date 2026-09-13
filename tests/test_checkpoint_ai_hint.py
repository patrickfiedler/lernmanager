"""AI hint after a wrong checkpoint answer (step 4 of the chemie agreement, request
2026-09-13 "Tipps je Frage"): /schueler/checkpoint/ki-hinweis, the hint log on
checkpoint_answer (migrate_059), and the export pairing with the next attempt.
"""
import json

import pytest

import app as app_module
import config
import llm_grading
import models

RUBRIC = "Beide Teile: Beobachtung und Schluss."
QUESTION_HINTS = ["Was hast du beobachtet?", "Was folgt daraus?"]
CHECKPOINT_HINTS = ["Allgemeiner Checkpoint-Tipp."]


def _quiz(**extra):
    question = {"type": "short_answer", "text": "Begründe die Flammenfarbe.",
                "rubric": RUBRIC, "hints": QUESTION_HINTS}
    question.update(extra)
    return {"questions": [question]}


def _setup(app, quiz):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "hinttest", "pw123")
    klasse_id = models.create_klasse("Chemie11")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Flammenfarben", "", "", "Chemie", "11/12", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Checkpoint: Flammenfarben", reihenfolge=0,
        quiz_json=json.dumps(quiz), checkpoint_type="quiz", kern_standard_tag="kern",
        checkpoint_hints_json=json.dumps(CHECKPOINT_HINTS),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, subtask_id


@pytest.fixture
def hint_calls(monkeypatch):
    """Grading always says wrong; the hint generator records what it was given."""
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(llm_grading, "grade_answer", lambda *a, **kw: {
        "correct": False, "feedback": "fehlt", "source": "llm",
        "prompt_version": "checkpoint:test"})
    calls = []
    # One-element list so a test can swap the reply (None, a report) before the call.
    reply = [{"text": "Was hast du genau gesehen?", "gap": "Beobachtung fehlt",
              "basis": 1, "report": False, "prompt_version": "checkpoint_hint:test"}]

    def fake(question_text, rubric, answer, hints, student_id=None):
        calls.append({"rubric": rubric, "answer": answer, "hints": hints})
        return reply[0]
    monkeypatch.setattr(llm_grading, "generate_checkpoint_hint", fake)
    return calls, reply


def _answer(client, subtask_id, text="Die Flamme ist gelb."):
    return client.post("/schueler/checkpoint/antwort", json={
        "slug": "flammenfarben", "subtask_id": subtask_id,
        "question_index": 0, "answer": text}).get_json()


def _hint(client, subtask_id, answer_id):
    return client.post("/schueler/checkpoint/ki-hinweis", json={
        "slug": "flammenfarben", "subtask_id": subtask_id,
        "question_index": 0, "answer_id": answer_id})


def _row(answer_id):
    with models.db_session() as conn:
        return dict(conn.execute("SELECT * FROM checkpoint_answer WHERE id = ?",
                                 (answer_id,)).fetchone())


def _login(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id


def test_wrong_answer_gets_hint_built_from_the_logged_row(app, client, hint_calls):
    calls, _ = hint_calls
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)

    verdict = _answer(client, subtask_id)
    assert verdict["correct"] is False
    data = _hint(client, subtask_id, verdict["answer_id"]).get_json()

    assert data["hint"] == "Was hast du genau gesehen?"
    assert data["report"] is False
    # The model got the question's own hints (not the checkpoint's) and the text as
    # logged -- the hint must fit what was graded.
    assert calls == [{"rubric": RUBRIC, "answer": "Die Flamme ist gelb.", "hints": QUESTION_HINTS}]
    row = _row(verdict["answer_id"])
    assert row["hint_status"] == "ok"
    assert row["hint_text"] == "Was hast du genau gesehen?"
    assert row["hint_gap"] == "Beobachtung fehlt"
    assert row["hint_basis"] == 1
    assert row["hint_source"] == "frage"
    assert row["hint_prompt_version"] == "checkpoint_hint:test"


def test_the_gap_never_reaches_the_student(app, client, hint_calls):
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    verdict = _answer(client, subtask_id)
    body = _hint(client, subtask_id, verdict["answer_id"]).get_data(as_text=True)
    assert "Beobachtung fehlt" not in body


def test_asking_twice_for_one_answer_costs_one_call(app, client, hint_calls):
    calls, _ = hint_calls
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    verdict = _answer(client, subtask_id)

    first = _hint(client, subtask_id, verdict["answer_id"]).get_json()
    second = _hint(client, subtask_id, verdict["answer_id"]).get_json()
    assert len(calls) == 1
    assert second["hint"] == first["hint"]


def test_stale_answer_id_gets_no_hint(app, client, hint_calls):
    calls, _ = hint_calls
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    old = _answer(client, subtask_id, "erste Antwort")
    _answer(client, subtask_id, "zweite Antwort")

    data = _hint(client, subtask_id, old["answer_id"]).get_json()
    assert data["hint"] is None
    assert calls == []


@pytest.mark.parametrize("extra", [{"zweiwertig": True}, {"bewertungsart": "begriff"}])
def test_two_answer_and_term_questions_get_no_ai_hint(app, client, hint_calls, extra):
    calls, _ = hint_calls
    student_id, subtask_id = _setup(app, _quiz(**extra))
    _login(client, student_id)
    verdict = _answer(client, subtask_id)

    assert _hint(client, subtask_id, verdict["answer_id"]).get_json()["hint"] is None
    assert calls == []
    assert _row(verdict["answer_id"])["hint_status"] is None
    # The page is told up front, so it never asks.
    page = client.get("/schueler/thema/flammenfarben/aufgabe-1/quiz").get_data(as_text=True)
    assert '"adaptive_hint": false' in page


def test_failed_call_is_logged_and_shows_nothing(app, client, hint_calls):
    _, result = hint_calls
    result[0] = None
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    verdict = _answer(client, subtask_id)

    assert _hint(client, subtask_id, verdict["answer_id"]).get_json()["hint"] is None
    assert _row(verdict["answer_id"])["hint_status"] == "error"


def test_spent_budget_is_logged_without_a_call(app, client, hint_calls, monkeypatch):
    calls, _ = hint_calls
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    verdict = _answer(client, subtask_id)

    monkeypatch.setattr(models, "check_llm_rate_limit",
                        lambda sid, usage_tag="llm_grading": usage_tag != "checkpoint_hint")
    assert _hint(client, subtask_id, verdict["answer_id"]).get_json()["hint"] is None
    assert calls == []
    assert _row(verdict["answer_id"])["hint_status"] == "limit"


def test_report_pointer_is_logged_as_melden(app, client, hint_calls):
    _, result = hint_calls
    result[0] = {"text": llm_grading.HINT_REPORT_TEXT, "gap": "Versuch fehlt",
                 "basis": None, "report": True, "prompt_version": "checkpoint_hint:test"}
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    verdict = _answer(client, subtask_id, "Versuch hab ich noch nicht gemacht")

    data = _hint(client, subtask_id, verdict["answer_id"]).get_json()
    assert data["report"] is True
    assert "Frage melden" in data["hint"]
    assert _row(verdict["answer_id"])["hint_status"] == "melden"


def test_reload_shows_last_wrong_answer_with_its_hint(app, client, hint_calls):
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    verdict = _answer(client, subtask_id)
    _hint(client, subtask_id, verdict["answer_id"])

    page = client.get("/schueler/thema/flammenfarben/aufgabe-1/quiz").get_data(as_text=True)
    assert '"answer_text": "Die Flamme ist gelb."' in page
    assert '"hint": "Was hast du genau gesehen?"' in page
    assert "Beobachtung fehlt" not in page


def test_button_hints_prefer_the_question_over_the_checkpoint(app, client, hint_calls):
    student_id, subtask_id = _setup(app, _quiz())
    _login(client, student_id)
    _answer(client, subtask_id)
    data = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "flammenfarben", "subtask_id": subtask_id, "question_index": 0}).get_json()
    assert data["hint"] == QUESTION_HINTS[0]


def test_button_hints_fall_back_to_the_checkpoint(app, client, hint_calls):
    quiz = _quiz()
    del quiz["questions"][0]["hints"]
    student_id, subtask_id = _setup(app, quiz)
    _login(client, student_id)
    _answer(client, subtask_id)
    data = client.post("/schueler/checkpoint/hinweis", json={
        "slug": "flammenfarben", "subtask_id": subtask_id, "question_index": 0}).get_json()
    assert data["hint"] == CHECKPOINT_HINTS[0]


def test_export_pairs_each_hint_with_the_next_attempt():
    answers = [
        {"correct": 0, "gave_up": 0, "hint_text": "Tipp A", "hint_status": "ok"},
        {"correct": 1, "gave_up": 0},
    ]
    first = app_module._hint_export_columns(answers, 0)
    assert first["ki_hinweis"] == "Tipp A"
    assert first["naechster_versuch_richtig"] == 1
    assert app_module._hint_export_columns(answers, 1)["naechster_versuch_richtig"] is None
    gave_up = [answers[0], {"correct": 0, "gave_up": 1}]
    assert app_module._hint_export_columns(gave_up, 0)["naechster_versuch_richtig"] == 0
    assert app_module._hint_export_columns([], 0)["ki_hinweis"] is None


class _FakeClient:
    def __init__(self, content):
        self.content = content
        self.chat = self
        self.completions = self

    def with_options(self, **kw):
        return self

    def create(self, **kw):
        return self.content


@pytest.mark.parametrize("payload, basis, report, text", [
    ({"luecke": "x", "tipp_basis": 2, "frage_melden": False, "text": "Frage?"}, 2, False, "Frage?"),
    # `true` is an int in Python -- it must not read as hint number 1.
    ({"luecke": "x", "tipp_basis": True, "frage_melden": False, "text": "Frage?"}, None, False, "Frage?"),
    ({"luecke": "x", "tipp_basis": 9, "frage_melden": False, "text": "Frage?"}, None, False, "Frage?"),
    ({"luecke": "x", "tipp_basis": None, "frage_melden": True, "text": ""}, None, True,
     llm_grading.HINT_REPORT_TEXT),
])
def test_generate_checkpoint_hint_parses_the_model_reply(monkeypatch, payload, basis, report, text):
    monkeypatch.setattr(llm_grading, "_get_client", lambda: _FakeClient(json.dumps(payload)))
    monkeypatch.setattr(llm_grading, "_message_text", lambda response: response)
    monkeypatch.setattr(models, "record_llm_usage", lambda *a, **kw: None)
    result = llm_grading.generate_checkpoint_hint("F", "K", "A", ["t1", "t2"])
    assert (result["basis"], result["report"], result["text"]) == (basis, report, text)
    assert result["prompt_version"].startswith("checkpoint_hint:")


def test_generate_checkpoint_hint_returns_none_on_empty_text(monkeypatch):
    payload = {"luecke": "x", "tipp_basis": 1, "frage_melden": False, "text": "  "}
    monkeypatch.setattr(llm_grading, "_get_client", lambda: _FakeClient(json.dumps(payload)))
    monkeypatch.setattr(llm_grading, "_message_text", lambda response: response)
    monkeypatch.setattr(models, "record_llm_usage", lambda *a, **kw: None)
    assert llm_grading.generate_checkpoint_hint("F", "K", "A", ["t1"]) is None
