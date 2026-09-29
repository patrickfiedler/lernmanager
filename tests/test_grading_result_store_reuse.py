"""Result store part 3 (grading-with-llm request 2026-09-18): criteria the
service reused from an earlier teacher correction arrive pre-reviewed.
Decision Patrick 2026-09-29: such a result stays in the review queue, last.
"""
import models
from tests.test_grading_review import _setup, _student

TEACHER = {"name": "Name", "score": 0, "max_score": 2, "reused": "teacher",
           "teacher_feedback": "Klammern löschen"}


def test_reused_fields_are_imported_and_count_as_confirmed(db):
    _, task_id, run_id, admin_id = _setup()
    sid = _student("Mueller", "Anna", "mueller.anna")
    rid = models.create_grading_result(run_id, task_id, sid, "mueller.anna",
                                       [dict(TEACHER, review_required=True),
                                        {"name": "Titel", "score": 1, "max_score": 1, "reused": "llm"}])
    c_teacher, c_llm = models.get_grading_result(rid)["criteria"]
    assert c_teacher["reused"] == "teacher"
    assert c_teacher["teacher_feedback"] == "Klammern löschen"
    assert c_teacher["confirmed"] is True
    assert c_llm["reused"] == "llm"
    # An always-review criterion answered by the teacher before no longer blocks release.
    models.release_grading_result(rid, admin_id)


def test_fully_pre_reviewed_result_is_last_in_queue_and_not_flagged(db):
    _, task_id, run_id, _ = _setup()
    r_pre = models.create_grading_result(run_id, task_id, _student("Aachen", "Pre", "aachen.pre"),
                                         "aachen.pre", [TEACHER])
    r_zero = models.create_grading_result(run_id, task_id, _student("Zimmer", "Zero", "zimmer.zero"),
                                          "zimmer.zero", [{"name": "Name", "score": 0, "max_score": 2}])
    r_clean = models.create_grading_result(run_id, task_id, _student("Bauer", "Clean", "bauer.clean"),
                                           "bauer.clean", [{"name": "Name", "score": 2, "max_score": 2}])

    queue = models.get_grading_run_review_queue(run_id)
    assert [r["id"] for r in queue] == [r_zero, r_clean, r_pre]
    assert not models.result_needs_attention(queue[-1])


def test_review_page_marks_reused_criterion(app, as_admin):
    _, task_id, run_id, _ = _setup()
    rid = models.create_grading_result(run_id, task_id, _student("Aachen", "Pre", "aachen.pre"),
                                       "aachen.pre", [TEACHER], document_file="doc.docx")
    html = as_admin.get(f"/admin/grading-result/{rid}/review").get_data(as_text=True)
    assert "♻ frühere Korrektur übernommen" in html
    assert "Klammern löschen" in html
