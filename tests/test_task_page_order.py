"""The Aufgabe page follows the student's working sequence, not the DB's field order.

Materialien used to render *below* the whole task card -- below the completion
checkbox -- although app.py already filters it to the current Aufgabe. A student was
asked to tick "Ich habe das geschafft" above the material needed to do the work.
The gate sat between `fertig_wenn` and the checkbox it qualifies, which is why three
CSS classes existed to fake one continuous card out of three siblings.

Order now: steps -> Materialien -> Hilfe -> gate -> fertig_wenn -> completion zone.
Machine check, then self-check, then commit.
"""
import json
import config
import models

GATE = {"format": [".docx"], "required_text": ["Fachraumregeln"]}


def _page(app, client, tmp_path, gate_passed):
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Alex", "Schueler", f"order{gate_passed}", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    gate_id = models.create_subtask(
        task_id, "Abgabe", reihenfolge=1,
        artifact_gate_json=json.dumps(GATE),
        fertig_wenn="Fertig wenn die Datei geprueft ist.",
        tipps="Sieh im Poster nach.",
    )
    models.create_material(task_id, "link", "https://example.org/poster.pdf", "Poster")
    models.assign_task_to_student(student_id, klasse_id, task_id)
    if gate_passed:
        st = models.get_student_task(student_id, klasse_id)
        models.save_artifact_gate_result(st["id"], gate_id, True)

    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    return client.get("/schueler/thema/testthema").get_data(as_text=True)


def _order(page, markers):
    at = {}
    for m in markers:
        assert m in page, f"{m} missing from the page"
        at[m] = page.index(m)
    return at


def test_working_sequence_on_a_passed_gate(app, client, tmp_path):
    page = _page(app, client, tmp_path, gate_passed=True)
    at = _order(page, ['class="task-content', 'materials-toggle', 'tipps-toggle',
                       'gate-card', 'fertig-wenn-callout', 'id="completion-zone"'])

    assert at['class="task-content'] < at['materials-toggle'], \
        "Materialien is the input to the work -- it belongs above, not below the checkbox"
    assert at['materials-toggle'] < at['tipps-toggle'], \
        "the help protocol says 'sieh in den Materialien nach' before asking for help"
    assert at['tipps-toggle'] < at['gate-card']
    assert at['gate-card'] < at['fertig-wenn-callout'], \
        "machine check first, then the self-check it feeds"
    assert at['fertig-wenn-callout'] < at['id="completion-zone"'], \
        "the criterion must sit directly on the checkbox that commits to it"


def test_criterion_closes_its_own_box_when_no_checkbox_follows(app, client, tmp_path):
    """A withheld completion zone leaves the callout as the last element -- it has to
    close its bottom edge instead of running into nothing."""
    page = _page(app, client, tmp_path, gate_passed=False)
    assert '<div id="completion-zone" hidden' in page
    assert "fertig-wenn-callout--standalone" in page


def test_hilfe_starts_open(app, client, tmp_path):
    page = _page(app, client, tmp_path, gate_passed=True)
    assert '<details class="tipps-toggle" open>' in page
