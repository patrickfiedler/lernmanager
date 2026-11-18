"""Warm-up answer log + LLM call metadata (migrate_082, chemie request 2026-11-18).

- every warm-up/practice answer gets a warmup_answer row with the history state
  from before it (the history row itself is overwritten)
- a practice session does not cancel the day's warm-up
- failed LLM calls are recorded (ok = 0) but do not count against the rate limit
"""
import config
import llm_grading
import models


def _log_rows(student_id):
    with models.db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM warmup_answer WHERE student_id = ? ORDER BY id", (student_id,))]


def test_each_answer_is_logged_with_state_before(db):
    student_id = models.create_student("Test", "Schüler", "logtest", "pw123")
    models.record_warmup_answer(student_id, 1, None, "h1", True, phase="warmup",
                                question_type="multiple_choice", grader="mc")
    models.record_warmup_answer(student_id, 1, None, "h1", False, phase="practice",
                                question_type="multiple_choice", grader="mc")
    first, second = _log_rows(student_id)
    assert first["phase"] == "warmup" and first["correct"] == 1
    assert first["days_since_last"] is None and first["streak_before"] is None
    assert second["phase"] == "practice" and second["correct"] == 0
    assert second["days_since_last"] == 0 and second["streak_before"] == 1


def test_practice_session_does_not_cancel_warmup(db):
    student_id = models.create_student("Test", "Schüler", "practicefirst", "pw123")
    models.save_warmup_session(student_id, 5, 4, session_type="practice")
    assert not models.has_done_warmup_today(student_id)
    models.save_warmup_session(student_id, 0, 0, skipped=True, session_type="warmup")
    assert models.has_done_warmup_today(student_id)


def test_failed_calls_do_not_use_up_the_rate_limit(db):
    student_id = models.create_student("Test", "Schüler", "failedcalls", "pw123")
    for _ in range(config.LLM_MAX_CALLS_PER_STUDENT_PER_HOUR):
        models.record_llm_usage(student_id, "llm_grading", ok=False, error="APITimeoutError")
    assert models.check_llm_rate_limit(student_id, "llm_grading")
    for _ in range(config.LLM_MAX_CALLS_PER_STUDENT_PER_HOUR):
        models.record_llm_usage(student_id, "llm_grading")
    assert not models.check_llm_rate_limit(student_id, "llm_grading")


def _usage_rows(student_id):
    with models.db_session() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM llm_usage WHERE student_id = ? ORDER BY id", (student_id,))]


def test_grade_answer_records_metadata(db, monkeypatch):
    student_id = models.create_student("Test", "Schüler", "llmmeta", "pw123")
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(llm_grading, "_call_llm", lambda *a, **k: {
        "correct": True, "feedback": "Gut.", "confidence": None,
        "usage": {"input_tokens": 120, "output_tokens": 30}})
    result = llm_grading.grade_answer("Frage", "Erwartet", "Antwort", student_id)
    assert result["source"] == "llm" and "usage" not in result

    def boom(*a, **k):
        raise TimeoutError("slow")
    monkeypatch.setattr(llm_grading, "_call_llm", boom)
    assert llm_grading.grade_answer("Frage", "Erwartet", "Antwort", student_id)["source"] == "fallback"

    ok_row, failed_row = _usage_rows(student_id)
    assert ok_row["ok"] == 1 and ok_row["model"] == config.LLM_MODEL
    assert ok_row["input_tokens"] == 120 and ok_row["output_tokens"] == 30
    assert ok_row["tokens_used"] == 150 and ok_row["latency_ms"] is not None
    assert ok_row["prompt_version"] == result["prompt_version"]
    assert failed_row["ok"] == 0 and failed_row["error"] == "TimeoutError"
