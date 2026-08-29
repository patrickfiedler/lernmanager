"""Per-class character-insert bar (klasse.zeichenleiste, migrate_052).

Asked for by Chemie 2026-08-29: on iPads the reaction arrow, subscripts and
superscript charges are unreachable, so students type "->" instead. The bar is
opt-in per class and must stay completely invisible everywhere else.
"""
import re

import config
import models


def _csrf_token(client):
    """CSRF is on in TESTING mode, so admin POSTs need a real token."""
    resp = client.get("/admin")
    match = re.search(r'name="csrf-token" content="([^"]+)"', resp.get_data(as_text=True))
    return match.group(1)


def _student_in_class(preset, name="11 Chemie"):
    klasse_id = models.create_klasse(name)
    models.set_klasse_zeichenleiste(klasse_id, preset)
    student_id = models.create_student("Muster", "Max", "happypanda", "bacado42")
    models.add_student_to_klasse(student_id, klasse_id)
    return student_id, klasse_id


def test_no_preset_means_no_characters(db):
    student_id, _ = _student_in_class(None)
    assert models.get_zeichenleiste_presets_for_student(student_id) == []


def test_preset_is_returned_for_the_student(db):
    student_id, _ = _student_in_class("chemie")
    assert models.get_zeichenleiste_presets_for_student(student_id) == ["chemie"]


def test_clearing_the_preset_turns_the_bar_off_again(db):
    student_id, klasse_id = _student_in_class("chemie")
    models.set_klasse_zeichenleiste(klasse_id, "")
    assert models.get_zeichenleiste_presets_for_student(student_id) == []


def test_only_the_students_own_classes_count(db):
    student_id, _ = _student_in_class(None)
    other = models.create_klasse("12 Chemie")
    models.set_klasse_zeichenleiste(other, "chemie")
    assert models.get_zeichenleiste_presets_for_student(student_id) == []


def test_two_classes_with_the_same_preset_are_not_duplicated(db):
    student_id, _ = _student_in_class("chemie")
    second = models.create_klasse("12 Chemie")
    models.set_klasse_zeichenleiste(second, "chemie")
    models.add_student_to_klasse(student_id, second)
    assert models.get_zeichenleiste_presets_for_student(student_id) == ["chemie"]


def test_context_processor_gives_the_student_the_characters(client):
    student_id, _ = _student_in_class("chemie")
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler")
    assert b"zeichenleiste.js" in resp.data
    assert "→".encode() in resp.data


def test_context_processor_is_silent_without_a_preset(client):
    student_id, _ = _student_in_class(None)
    with client.session_transaction() as sess:
        sess["student_id"] = student_id
    resp = client.get("/schueler")
    assert b"zeichenleiste.js" not in resp.data


def test_admins_never_get_the_bar(as_admin, db=None):
    """An admin previewing a student page should see the page, not a teacher-only
    affordance -- and admins do not answer quizzes at all."""
    klasse_id = models.create_klasse("11 Chemie")
    models.set_klasse_zeichenleiste(klasse_id, "chemie")
    resp = as_admin.get(f"/admin/klasse/{klasse_id}")
    assert b"js/zeichenleiste.js" not in resp.data


def test_admin_route_rejects_an_unknown_preset(as_admin):
    klasse_id = models.create_klasse("11 Chemie")
    as_admin.post(f"/admin/klasse/{klasse_id}/zeichenleiste",
                  data={"preset": "klingonisch", "csrf_token": _csrf_token(as_admin)},
                  follow_redirects=True)
    with models.db_session() as conn:
        row = conn.execute("SELECT zeichenleiste FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
    assert row["zeichenleiste"] is None


def test_admin_route_stores_a_known_preset(as_admin):
    klasse_id = models.create_klasse("11 Chemie")
    as_admin.post(f"/admin/klasse/{klasse_id}/zeichenleiste",
                  data={"preset": "chemie", "csrf_token": _csrf_token(as_admin)},
                  follow_redirects=True)
    with models.db_session() as conn:
        row = conn.execute("SELECT zeichenleiste FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
    assert row["zeichenleiste"] == "chemie"


def test_chemie_set_covers_what_the_students_could_not_type(db):
    """The 2026-08-26 export had no arrow, no subscript and no charge sign in any
    of thirty half-equation answers. Those three are the point of the set."""
    chars = config.CHARACTER_SETS["chemie"]["chars"]
    assert "→" in chars      # reaction arrow
    assert "₂" in chars      # subscript 2 (I2)
    assert "⁻" in chars      # superscript minus (I-)
