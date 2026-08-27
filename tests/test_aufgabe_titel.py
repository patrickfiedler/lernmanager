"""Aufgabe descriptions are Markdown; their title must render as plain text.

Found 2026-08-27: the Checkpoint-Prüfung collapsible showed "### Checkpoint
Kernladung" next to the student's name. The template ran the description through
`striptags`, which removes HTML but leaves Markdown untouched, so the hashes
survived into a plain-text label.

The same "leading ### is the title" rule already existed inline in the dashboard's
next-task preview; both now go through app.aufgabe_titel().
"""
import app as app_module


def test_leading_h3_becomes_the_title():
    assert app_module.aufgabe_titel("### Checkpoint Kernladung\n\n🎯 Ziel: x") \
        == "Checkpoint Kernladung"


def test_any_heading_depth_is_stripped():
    for hashes in ("#", "##", "###", "####"):
        assert app_module.aufgabe_titel(f"{hashes} Titel\nrest") == "Titel"


def test_description_without_a_heading_falls_back_to_the_first_line():
    assert app_module.aufgabe_titel("Kein Heading hier\nzweite Zeile") == "Kein Heading hier"


def test_fallback_line_is_truncated_but_a_heading_is_not():
    """The dashboard preview relied on the fallback being capped; a heading is
    already short and gets truncated by the template that displays it."""
    long_line = "x" * 200
    assert len(app_module.aufgabe_titel(long_line)) == 80
    assert app_module.aufgabe_titel("### " + "y" * 200) == "y" * 200


def test_empty_and_none_are_safe():
    assert app_module.aufgabe_titel("") == ""
    assert app_module.aufgabe_titel(None) == ""


def test_registered_as_a_template_filter():
    assert "aufgabe_titel" in app_module.app.jinja_env.filters


def test_review_page_shows_no_markdown_hashes(app, client):
    """End-to-end: the label the bug was reported against."""
    import json
    import models
    app.config["WTF_CSRF_ENABLED"] = False
    klasse_id = models.create_klasse("11c")
    student_id = models.create_student("Muster", "Kaya", "hp", "pw123")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("1 - Atommodelle", "", "", "Chemie", "11", "")
    subtask_id = models.create_subtask(
        task_id, "### Checkpoint Kernladung\n\n🎯 Ziel: etwas", reihenfolge=0,
        quiz_json=json.dumps({"questions": []}), checkpoint_type="quiz")
    models.create_checkpoint_attempt(
        student_id, subtask_id, task_id, "quiz", "kern",
        score=2, attempt_count=1, hint_count=0, session_uid="s1")

    with client.session_transaction() as sess:
        sess["admin_id"] = 1
    html = client.get("/admin/checkpoint-pruefung").get_data(as_text=True)

    assert "Checkpoint Kernladung" in html, "title missing entirely"
    assert "### Checkpoint" not in html
