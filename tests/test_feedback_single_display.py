"""Each gate card owns exactly ONE persisted feedback display.

Feedback was rendered in three places at once: the card's own block, the live
AJAX result, and a flat copy inside the "Deine Datei" fold-out
(_artifact_file_details.html). The fold-out copy is gone; the inline gate now
has its own block instead of borrowing the fold-out's.
"""
import json
import os
import config
import models

GATE_CONFIG = {"format": [".txt", ".md"]}
GRADED_CONFIG = {"format": [".txt", ".md"], "criteria": ["Enthaelt eine Einleitung"]}
FEEDBACK = [{"criterion": "Enthaelt eine Einleitung", "passed": False,
             "note": "Fehlt noch.", "source": "llm"}]


def _setup(app, tmp_path, n_subtasks):
    """n_subtasks=1 -> the gate is the capstone; 2 -> gate is inline (not last)."""
    app.config["WTF_CSRF_ENABLED"] = False
    config.UPLOAD_FOLDER = str(tmp_path / "uploads")

    student_id = models.create_student("Alex", "Schueler", f"fbtest{n_subtasks}", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "pflicht")
    gate_id = models.create_subtask(
        task_id, "Abgabe", reihenfolge=1,
        artifact_gate_json=json.dumps(GATE_CONFIG),
        graded_artifact_json=json.dumps(GRADED_CONFIG),
    )
    for i in range(1, n_subtasks):
        models.create_subtask(task_id, f"Danach {i}", reihenfolge=1 + i)

    models.assign_task_to_student(student_id, klasse_id, task_id)
    student_task = models.get_student_task(student_id, klasse_id)
    models.save_artifact_gate_result(student_task["id"], gate_id, True)
    models.save_artifact_feedback(student_id, gate_id, FEEDBACK)

    # The fold-out only renders feedback when a real upload exists on disk AND
    # the class has LLM feedback on -- without both, this test proves nothing.
    models.set_klasse_llm_feedback(klasse_id, True)
    artefakte = os.path.join(str(tmp_path / "uploads"), "artefakte")
    os.makedirs(artefakte, exist_ok=True)
    disk_filename = f"{student_id}_{task_id}.txt"
    with open(os.path.join(artefakte, disk_filename), "w") as f:
        f.write("Meine Abgabe")
    models.save_student_artifact_file(student_id, task_id, gate_id, "abgabe.txt", disk_filename)
    return student_id


def _page(client, student_id):
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    return client.get("/schueler/thema/testthema").get_data(as_text=True)


def test_capstone_card_has_exactly_one_feedback_block(app, client, tmp_path):
    html = _page(client, _setup(app, tmp_path, 1))

    assert html.count('id="capstone-gate-feedback-data"') == 1
    # The fold-out must not repeat it in the old flat style.
    assert html.count("Enthaelt eine Einleitung") == 1


def test_inline_card_renders_its_own_feedback_block(app, client, tmp_path):
    html = _page(client, _setup(app, tmp_path, 2))

    assert 'id="inline-gate-feedback-data"' in html
    assert html.count("Enthaelt eine Einleitung") == 1


def test_foldout_never_renders_the_flat_feedback_list(app, client, tmp_path):
    """The flat renderer's signature markup, only ever emitted by the fold-out."""
    html = _page(client, _setup(app, tmp_path, 1))
    assert 'class="artifact-checklist" style="margin-top:0.75rem;"' not in html


def test_foldout_flat_list_gone_for_inline_gate_too(app, client, tmp_path):
    html = _page(client, _setup(app, tmp_path, 2))
    assert 'class="artifact-checklist" style="margin-top:0.75rem;"' not in html
