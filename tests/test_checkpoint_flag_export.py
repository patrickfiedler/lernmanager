"""Reports in the two checkpoint exports (CSV + JSON).

Chemie reads these files; a report has to arrive as structured fields, not as a
sentence buried in a teacher's note.
"""
import json
import models

QUIZ = {
    "questions": [
        {"text": "Frage 1", "options": ["richtig", "falsch"], "correct": [0]},
        {"text": "Frage 2", "options": ["richtig", "falsch"], "correct": [0]},
    ]
}


def _session_with_report(app, client):
    app.config["WTF_CSRF_ENABLED"] = False
    student_id = models.create_student("Test", "Schueler", "flagexport", "pw123")
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
        "reason_code": "technisch", "reason_text": "Das Bild fehlt",
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


def test_json_export_carries_the_report_as_fields(app, client, as_admin):
    _session_with_report(app, client)

    export = json.loads(as_admin.get("/admin/checkpoint-pruefung/export.json").get_data(as_text=True))
    session = export["sessions"][0]
    assert session["score_vorlaeufig"] is True

    reported = [q for q in session["fragen"] if q["meldungen"]]
    assert len(reported) == 1
    meldung = reported[0]["meldungen"][0]
    assert meldung["grund_code"] == "technisch"
    assert meldung["grund_text"] == "Das Bild fehlt"
    assert meldung["status"] == "offen"
    assert meldung["quelle"] == "student"
    assert reported[0]["punkte"] is None


def test_csv_export_keeps_a_report_that_has_no_answer(app, client, as_admin):
    """The question was reported without typing anything -- the commonest case, and
    the one where the report is the only thing there is to export."""
    _session_with_report(app, client)

    body = as_admin.get("/admin/checkpoint-pruefung/export.csv").get_data(as_text=True)
    lines = [line for line in body.splitlines() if line.strip()]
    header = lines[0].split(";")
    assert "meldung_grund" in header

    reported_rows = [line for line in lines[1:] if "Das Bild fehlt" in line]
    assert len(reported_rows) == 1
    # Every row must carry the same columns, or the spreadsheet shifts.
    assert all(len(line.split(";")) == len(header) for line in lines[1:])
