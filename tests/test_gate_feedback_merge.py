"""A passed gate shows its deterministic hits AND the criteria feedback, not one or
the other.

Reported by MBI 2026-08-30 from production: an upload that passed cleanly and produced
six `matches` displayed none of them -- the "Gut so" column was empty. The two sources
were mutually exclusive in the client (`if (data.llm_feedback...) ... else ...`), and
llm_feedback practically always wins, because `_build_level2_feedback()` runs the
deterministic filename check on every passed gate with a `graded_artifact`, regardless
of the class's LLM toggle. Affected every unit carrying `artifact_gate` and
`graded_artifact` at once, correct filename included.
"""
import io
import json
import os
import re
import config
import models

from tests.test_artifact_extraction import make_docx

# A .docx, because check_gate() only reads the real document formats -- a .txt
# passes unconditionally with no matches, which is not the case this pins.
GATE_CONFIG = {
    "format": [".docx"],
    "required_text": ["Fachraumregeln"],
    "forbidden_text": ["______"],
}
GRADED_CONFIG = {
    "format": [".docx"],
    "expected_filename": "Abgabe-Alex",
    "criteria": ["Enthaelt eine Einleitung"],
}
BODY = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        '<w:r><w:t>Fachraumregeln</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Keine Getränke am PC.</w:t></w:r></w:p>')

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates', 'student', 'klasse.html')


def _student_with_gate_and_criteria(app, tmp_path):
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Alex", "Schueler", "mergetest", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    subtask_id = models.create_subtask(
        task_id, "Aufgabe mit Abgabe-Pruefung", reihenfolge=1,
        artifact_gate_json=json.dumps(GATE_CONFIG),
        graded_artifact_json=json.dumps(GRADED_CONFIG),
    )
    models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, klasse_id, task_id, subtask_id


def _post_passing_upload(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    return client.post(
        "/schueler/thema/testthema/aufgabe-1/abgabe-pruefen",
        data={"file": (io.BytesIO(make_docx(BODY)), "Abgabe-Alex.docx")},
        content_type="multipart/form-data",
    )


def test_passed_gate_returns_both_sources(app, client, tmp_path):
    """The response has to carry the structural hits alongside llm_feedback --
    the client can only merge what it receives."""
    student_id, _, _, _ = _student_with_gate_and_criteria(app, tmp_path)
    body = _post_passing_upload(client, student_id).get_json()

    assert body["passed"] is True
    assert len(body["matches"]) == 2, body["matches"]
    assert any("Fachraumregeln" in m for m in body["matches"])
    assert body["llm_feedback"], "filename check runs on every passed graded gate"


def test_passed_gate_reports_that_the_filename_was_checked(app, client, tmp_path):
    """The client's own keyword check is a fallback. Without this flag it would stack
    a second, looser filename line on top of the exact one -- and the two can disagree."""
    student_id, _, _, _ = _student_with_gate_and_criteria(app, tmp_path)
    body = _post_passing_upload(client, student_id).get_json()

    assert body["filename_checked"] is True
    assert sum(1 for i in body["llm_feedback"]
               if i["criterion"].startswith("Dateiname")) == 1


def _source():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read()


def test_client_merges_instead_of_choosing():
    """Source-level guard: no Flask response reveals which branch the card rendered.
    Both gates must go through allFeedbackItems(), and the old either/or must be gone."""
    source = _source()
    assert "function allFeedbackItems(" in source
    calls = re.findall(r"renderFeedbackSplit\(allFeedbackItems\(data, filenameItem\)\)", source)
    assert len(calls) == 4, "expected 4 call sites (2 gates x pass/fail)"
    assert "renderFeedbackSplit(data.llm_feedback)" not in source, \
        "rendering llm_feedback alone drops every structural gate hit"
    assert not re.search(r"if \(data\.llm_feedback && data\.llm_feedback\.length\)", source), \
        "the two feedback sources are merged now, not chosen between"


def test_merge_keeps_gate_hits_first():
    """Deterministic facts before the LLM's judgement -- and the keyword fallback is
    dropped exactly when the server already ran the exact check."""
    source = _source()
    fn = re.search(r"function allFeedbackItems\(data, filenameItem\) \{(.*?)\n\}", source, re.S)
    assert fn, "allFeedbackItems not found"
    body = fn.group(1)
    assert "data.filename_checked ? null : filenameItem" in body
    assert body.index("gateFeedbackItems") < body.index("data.llm_feedback")
