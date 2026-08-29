"""Character-insert bar above free-text answer fields.

Asked for by Chemie 2026-08-29: on iPads the reaction arrow, subscripts and
superscript charges are unreachable, so students type "->". The bar follows the
*Thema* -- it appears on a Chemie unit and nowhere else, including for a student
whose other classes are Chemie. `klasse` has no `fach` column anyway; the subject
lives on the Thema, and one real class runs Chemie and MBI side by side.
"""
import json

import config
import models


def _student():
    klasse_id = models.create_klasse("Klasse x")
    student_id = models.create_student("Muster", "Max", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    return student_id, klasse_id


def _topic(student_id, klasse_id, fach, name=None, quiz=None, rolle="primary"):
    task_id = models.create_task(name or f"Thema {fach}", "", "", fach, "11/12", "pflicht",
                                 quiz_json=json.dumps(quiz) if quiz else None)
    models.assign_task_to_student(student_id, klasse_id, task_id, rolle=rolle)
    return task_id


FILL_QUIZ = {"questions": [{"type": "fill_blank", "text": "2 I___ wird oxidiert.",
                            "answers": ["-"]}]}


def test_the_map_reaches_a_students_page(client):
    student_id, _ = _student()
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler")
    assert b"zeichenleiste.js" in resp.data
    assert "→".encode() in resp.data


def test_admins_get_no_map_at_all(as_admin):
    """An admin previewing a student page should see the page, not a
    student-only affordance -- and admins do not answer quizzes."""
    klasse_id = models.create_klasse("11 Chemie")
    resp = as_admin.get(f"/admin/klasse/{klasse_id}")
    assert b"js/zeichenleiste.js" not in resp.data


def test_a_chemie_quiz_page_names_its_subject(client):
    student_id, klasse_id = _student()
    _topic(student_id, klasse_id, "Chemie", name="Elektrolyse", quiz=FILL_QUIZ)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler/thema/elektrolyse/quiz")
    assert b'data-zeichenleiste-fach="Chemie"' in resp.data


def test_an_mbi_quiz_page_names_a_subject_with_no_characters(client):
    """The attribute is still there -- the bar is decided client-side by looking
    the subject up in the map, and MBI simply has no entry."""
    student_id, klasse_id = _student()
    _topic(student_id, klasse_id, "MBI", name="Dateien", quiz=FILL_QUIZ)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler/thema/dateien/quiz")
    assert b'data-zeichenleiste-fach="MBI"' in resp.data
    assert "MBI" not in config.CHARACTER_SETS


def test_a_students_chemie_class_does_not_bleed_into_their_mbi_unit(client):
    """The point of moving from class to Thema: this student does Chemie, but
    this page is MBI and must show no chemistry symbols."""
    student_id, klasse_id = _student()
    _topic(student_id, klasse_id, "Chemie", name="Elektrolyse", quiz=FILL_QUIZ)
    _topic(student_id, klasse_id, "MBI", name="Dateien", quiz=FILL_QUIZ, rolle="secondary")
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler/thema/dateien/quiz")
    assert b'data-zeichenleiste-fach="MBI"' in resp.data
    assert b'data-zeichenleiste-fach="Chemie"' not in resp.data


def test_class_unlocked_practice_entries_carry_the_subject(db):
    student_id, klasse_id = _student()
    chemie = _topic(student_id, klasse_id, "Chemie", name="Elektrolyse", quiz=FILL_QUIZ)
    models.set_practice_unlock_for_class(klasse_id, chemie, True)
    pool = models.get_warmup_question_pool(student_id)
    assert pool, "class-unlocked topic should enter the pool without an attempt"
    assert all(entry["fach"] == "Chemie" for entry in pool)


def test_a_mixed_practice_pool_tags_each_question_separately(db):
    """The reason the subject rides on the question: one practice run can pull a
    Chemie and an MBI question, and the bar has to appear on one and not the other."""
    student_id, klasse_id = _student()
    chemie = _topic(student_id, klasse_id, "Chemie", name="Elektrolyse", quiz=FILL_QUIZ)
    mbi = _topic(student_id, klasse_id, "MBI", name="Dateien", quiz=FILL_QUIZ, rolle="secondary")
    models.set_practice_unlock_for_class(klasse_id, chemie, True)
    models.set_practice_unlock_for_class(klasse_id, mbi, True)
    by_topic = {e["topic_name"]: e["fach"] for e in models.get_warmup_question_pool(student_id)}
    assert by_topic == {"Elektrolyse": "Chemie", "Dateien": "MBI"}


def test_only_chemie_defines_a_character_set(db):
    """Every other subject stays unaffected -- the bar is opt-in by being listed
    here, not opt-out."""
    assert set(config.CHARACTER_SETS) == {"Chemie"}
    assert "Chemie" in config.SUBJECTS


def test_chemie_set_covers_what_the_students_could_not_type(db):
    """The 2026-08-26 export had no arrow, no subscript and no charge sign in any
    of thirty half-equation answers. Those three are the point of the set."""
    chars = config.CHARACTER_SETS["Chemie"]
    assert "→" in chars      # reaction arrow
    assert "₂" in chars      # subscript 2 (I2)
    assert "⁻" in chars      # superscript minus (I-)
