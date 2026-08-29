"""Character-insert bar above free-text answer fields.

Asked for by Chemie 2026-08-29: on iPads the reaction arrow, subscripts and
superscript charges are unreachable, so students type "->". The bar follows the
*subject* -- Chemie only -- and must stay invisible everywhere else.

Why subject and not a per-class setting: `klasse` has no `fach` column, the
subject lives on the Thema, and one real class runs Chemie and MBI together.
"""
import re

import config
import models


def _csrf_token(client):
    """CSRF is on in TESTING mode, so admin POSTs need a real token."""
    resp = client.get("/admin")
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1)


def _student_with_topic(fach=None, klassenname="11 Chemie"):
    """A student in a class, optionally with one Thema of `fach` assigned in it."""
    klasse_id = models.create_klasse(klassenname)
    student_id = models.create_student("Muster", "Max", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    if fach:
        task_id = models.create_task(f"Thema {fach}", "", "", fach, "11/12", "pflicht")
        models.assign_task_to_student(student_id, klasse_id, task_id)
    return student_id, klasse_id


def test_a_class_without_any_thema_has_no_subject(db):
    student_id, _ = _student_with_topic(None)
    assert models.get_faecher_for_student(student_id) == []


def test_an_assigned_chemie_thema_makes_the_class_chemie(db):
    student_id, _ = _student_with_topic("Chemie")
    assert models.get_faecher_for_student(student_id) == ["Chemie"]


def test_a_mixed_class_reports_both_subjects(db):
    """"Klasse x" in production runs Chemie and MBI side by side -- a single
    declared class subject would be wrong for it."""
    student_id, klasse_id = _student_with_topic("Chemie", klassenname="Klasse x")
    mbi = models.create_task("Thema MBI", "", "", "MBI", "11/12", "pflicht")
    models.assign_task_to_student(student_id, klasse_id, mbi, rolle="secondary")
    assert models.get_faecher_for_student(student_id) == ["Chemie", "MBI"]


def test_another_classes_chemie_thema_does_not_leak(db):
    student_id, _ = _student_with_topic(None)
    other_id = models.create_klasse("12 Chemie")
    other_student = models.create_student("Neben", "An", "bravebear", "kodema17")
    models.add_student_to_klasse(other_student, other_id)
    task_id = models.create_task("Elektrolyse", "", "", "Chemie", "11/12", "pflicht")
    models.assign_task_to_student(other_student, other_id, task_id)
    assert models.get_faecher_for_student(student_id) == []


def test_chemie_student_gets_the_characters(client):
    student_id, _ = _student_with_topic("Chemie")
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler")
    assert b"zeichenleiste.js" in resp.data
    assert "→".encode() in resp.data


def test_mbi_student_gets_nothing(client):
    student_id, _ = _student_with_topic("MBI", klassenname="Klasse 6y")
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler")
    assert b"zeichenleiste.js" not in resp.data


def test_student_without_any_thema_gets_nothing(client):
    student_id, _ = _student_with_topic(None)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler")
    assert b"zeichenleiste.js" not in resp.data


def test_admins_never_get_the_bar(as_admin):
    """An admin previewing a student page should see the page, not a
    student-only affordance -- and admins do not answer quizzes at all."""
    klasse_id = models.create_klasse("11 Chemie")
    resp = as_admin.get(f"/admin/klasse/{klasse_id}")
    assert b"js/zeichenleiste.js" not in resp.data


def test_only_chemie_defines_a_character_set(db):
    """Every other subject must stay unaffected -- the bar is opt-in by being
    listed here, not opt-out."""
    assert set(config.CHARACTER_SETS) == {"Chemie"}
    assert "Chemie" in config.SUBJECTS


def test_chemie_set_covers_what_the_students_could_not_type(db):
    """The 2026-08-26 export had no arrow, no subscript and no charge sign in any
    of thirty half-equation answers. Those three are the point of the set."""
    chars = config.CHARACTER_SETS["Chemie"]
    assert "→" in chars      # reaction arrow
    assert "₂" in chars      # subscript 2 (I2)
    assert "⁻" in chars      # superscript minus (I-)
