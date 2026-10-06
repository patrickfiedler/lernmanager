"""A question taken out of the grading counts for nobody, and nothing is rewritten.

Patrick, 2026-10-06 (trigger: 1.7, three of four questions reported by most of the
course). Decided: stored points stay, every reader skips the question; it drops out
for everyone, also for those who solved it; students read "zählt nicht".
"""
import json

import pytest

import checkpoint_overview
import models

QUIZ = {"questions": [
    {"type": "short_answer", "text": "Frage A", "rubric": "a"},
    {"type": "short_answer", "text": "Frage B", "rubric": "b"},
    {"type": "short_answer", "text": "Frage C", "rubric": "c"},
]}


@pytest.fixture
def data(app):
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11z")
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11", "")
    cp = models.create_subtask(
        task_id, "### 1.7 - Grenzen", reihenfolge=0, quiz_json=json.dumps(QUIZ),
        checkpoint_type="quiz", kern_standard_tag="kern")
    students = []
    for i, name in enumerate(["Adler", "Bach"]):
        sid = models.create_student(name, "Kim", f"user{i}", "bacado42")
        models.add_student_to_klasse(sid, klasse_id)
        models.assign_task_to_student(sid, klasse_id, task_id)
        students.append(sid)
    return {"klasse_id": klasse_id, "task_id": task_id, "cp": cp, "students": students}


def _sit(data, student_id, scores):
    counted = [v for v in scores.values() if v is not None]
    return models.create_checkpoint_attempt(
        student_id, data["cp"], data["task_id"], "quiz", "kern",
        score=min(counted) if counted else 0, attempt_count=1, hint_count=0,
        quiz_snapshot_json=json.dumps(QUIZ), session_uid=f"s-{student_id}",
        question_scores_json=json.dumps(scores))


def _overview(data):
    students, subtasks, attempts, pending = models.get_checkpoint_overview_data(
        data["klasse_id"], data["task_id"])
    excluded = models.get_excluded_questions([s["id"] for s in subtasks])
    checkpoints = [{"id": s["id"], "titel": "x", "kern": True,
                    "questions": [q["text"] for q in json.loads(s["quiz_json"])["questions"]]}
                   for s in subtasks]
    scores = {a["id"]: json.loads(a["question_scores_json"]) for a in attempts.values()}
    return checkpoint_overview.build_overview(
        students, checkpoints, attempts, scores, excluded, pending)


def test_excluding_lifts_the_session_score_without_rewriting_it(data):
    attempt_id = _sit(data, data["students"][0], {"0": 3, "1": 0, "2": 2})
    attempt = models.get_checkpoint_attempt(attempt_id)
    assert models.effective_checkpoint_score(attempt) == 0

    models.set_question_excluded(data["cp"], 1, True)
    attempt = models.get_checkpoint_attempt(attempt_id)
    assert models.effective_checkpoint_score(attempt) == 2
    assert attempt["score"] == 0                                   # stored: untouched
    assert json.loads(attempt["question_scores_json"])["1"] == 0

    models.set_question_excluded(data["cp"], 1, False)             # and back
    assert models.effective_checkpoint_score(models.get_checkpoint_attempt(attempt_id)) == 0


def test_a_teacher_override_still_wins(data):
    attempt_id = _sit(data, data["students"][0], {"0": 3, "1": 0, "2": 3})
    models.set_question_excluded(data["cp"], 1, True)
    attempt = dict(models.get_checkpoint_attempt(attempt_id), teacher_score=2)
    assert models.effective_checkpoint_score(attempt) == 2


def test_overview_sums_and_missing(data):
    a, b = data["students"]
    _sit(data, a, {"0": 3, "1": 3, "2": 2})
    # b never sat the checkpoint
    rows = {r["student"]["id"]: r for r in _overview(data)["rows"]}
    assert (rows[a]["points"], rows[a]["max"], rows[a]["fehlend"]) == (8, 9, 0)
    assert (rows[b]["points"], rows[b]["max"], rows[b]["fehlend"]) == (0, 9, 3)


def test_excluded_question_leaves_sum_maximum_and_missing_for_everyone(data):
    """Also for the one who solved it cleanly -- one rule, one denominator."""
    a, b = data["students"]
    _sit(data, a, {"0": 3, "1": 3, "2": 2})
    models.set_question_excluded(data["cp"], 1, True)
    overview = _overview(data)
    rows = {r["student"]["id"]: r for r in overview["rows"]}
    assert (rows[a]["points"], rows[a]["max"]) == (5, 6)
    assert (rows[b]["max"], rows[b]["fehlend"]) == (6, 2)
    assert rows[a]["cells"][1] == {"state": "ausgeschlossen", "points": 3}
    assert (overview["counted_questions"], overview["excluded_questions"]) == (2, 1)


def test_an_open_report_is_neither_points_nor_missing(data):
    a = data["students"][0]
    attempt_id = _sit(data, a, {"0": 3, "1": None, "2": 3})
    models.create_checkpoint_flag(data["cp"], 1, "student", student_id=a,
                                  checkpoint_attempt_id=attempt_id)
    row = _overview(data)["rows"][0]
    assert (row["points"], row["max"], row["fehlend"], row["offen"]) == (6, 6, 0, 1)
    assert models.checkpoint_score_is_provisional({"id": attempt_id})


def test_a_report_on_an_excluded_question_waits_on_nobody(data):
    a = data["students"][0]
    attempt_id = _sit(data, a, {"0": 3, "1": None, "2": 3})
    models.create_checkpoint_flag(data["cp"], 1, "student", student_id=a,
                                  checkpoint_attempt_id=attempt_id, status="abgelehnt")
    assert models.get_checkpoints_awaiting_retry(a)
    models.set_question_excluded(data["cp"], 1, True)
    assert not models.checkpoint_score_is_provisional({"id": attempt_id})
    assert not models.get_checkpoints_awaiting_retry(a)
    assert not models.get_flags_for_retry(a, data["cp"])
    assert _overview(data)["rows"][0]["offen"] == 0


def test_admin_page_and_switch(data, as_admin):
    a = data["students"][0]
    _sit(data, a, {"0": 3, "1": 0, "2": 2})
    url = f"/admin/checkpoint-uebersicht?klasse_id={data['klasse_id']}"
    body = as_admin.get(url).get_data(as_text=True)
    assert "Adler, Kim" in body and "Nicht werten" in body

    as_admin.post(f"/admin/checkpoint-uebersicht/frage/{data['cp']}/1/wertung",
                  data={"ausschliessen": "1", "grund": "Bild fehlte"})
    assert 1 in models.get_excluded_questions()[data["cp"]]
    body = as_admin.get(url).get_data(as_text=True)
    assert "Wieder werten" in body and "Bild fehlte" in body

    as_admin.post(f"/admin/checkpoint-uebersicht/frage/{data['cp']}/1/wertung",
                  data={"ausschliessen": "0"})
    assert not models.get_excluded_questions()


def test_student_reads_zaehlt_nicht(data, client):
    a = data["students"][0]
    _sit(data, a, {"0": 3, "1": 0, "2": 2})
    models.set_question_excluded(data["cp"], 1, True)
    with client.session_transaction() as sess:
        sess["student_id"] = a
    body = client.get("/schueler/checkpoints").get_data(as_text=True)
    assert "F2 –" in body
