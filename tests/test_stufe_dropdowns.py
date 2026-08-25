"""Admin topic dropdowns group exact grade matches above everything else.

Classes without a klassenstufe keep the old flat list.
"""
import models


def _seed(klassenstufe):
    klasse_id = models.create_klasse("6a")
    if klassenstufe:
        models.update_klasse_klassenstufe(klasse_id, klassenstufe)
    passend = models.create_task("Passend", "", "", "MBI", "6", "pflicht")
    fremd = models.create_task("Fremd", "", "", "MBI", "8", "pflicht")
    return klasse_id, passend, fremd


def _positions(html, *needles):
    return [html.index(n) for n in needles]


def test_klasse_detail_groups_matching_grade_first(as_admin, db):
    klasse_id, _, _ = _seed(6)
    html = as_admin.get(f"/admin/klasse/{klasse_id}").get_data(as_text=True)

    assert "Passend zur Klassenstufe" in html
    assert "Andere Klassenstufen" in html
    match_pos, passend, other_pos, fremd = _positions(
        html, "Passend zur Klassenstufe", "MBI (6): Passend",
        "Andere Klassenstufen", "MBI (8): Fremd")
    assert match_pos < passend < other_pos < fremd


def test_klasse_detail_without_klassenstufe_stays_flat(as_admin, db):
    klasse_id, _, _ = _seed(None)
    html = as_admin.get(f"/admin/klasse/{klasse_id}").get_data(as_text=True)

    assert "Passend zur Klassenstufe" not in html
    assert "MBI (6): Passend" in html
    assert "MBI (8): Fremd" in html


def test_legacy_double_year_topic_still_matches(as_admin, db):
    klasse_id, _, _ = _seed(6)
    models.create_task("Alt", "", "", "MBI", "5/6", "pflicht")
    html = as_admin.get(f"/admin/klasse/{klasse_id}").get_data(as_text=True)

    match_pos, alt, other_pos = _positions(
        html, "Passend zur Klassenstufe", "MBI (5/6): Alt", "Andere Klassenstufen")
    assert match_pos < alt < other_pos


def test_topic_queue_groups_matching_grade_first(as_admin, db):
    klasse_id, _, _ = _seed(6)
    html = as_admin.get(f"/admin/klasse/{klasse_id}/themen-reihenfolge").get_data(as_text=True)

    match_pos, passend, other_pos, fremd = _positions(
        html, "Passend zur Klassenstufe", "MBI (6): Passend",
        "Andere Klassenstufen", "MBI (8): Fremd")
    assert match_pos < passend < other_pos < fremd


def test_schueler_detail_groups_by_students_classes(as_admin, db):
    klasse_id, _, _ = _seed(6)
    student_id = models.create_student("Muster", "Max", "maxmuster", "pw12ab34")
    models.add_student_to_klasse(student_id, klasse_id)

    html = as_admin.get(f"/admin/schueler/{student_id}").get_data(as_text=True)

    match_pos, passend, other_pos, fremd = _positions(
        html, "Passend zur Klassenstufe", "MBI (6): Passend",
        "Andere Klassenstufen", "MBI (8): Fremd")
    assert match_pos < passend < other_pos < fremd


def test_practice_unlock_dropdown_excludes_already_unlocked(as_admin, db):
    klasse_id, passend, fremd = _seed(6)
    models.set_practice_unlock_for_class(klasse_id, passend, True)

    html = as_admin.get(f"/admin/klasse/{klasse_id}").get_data(as_text=True)
    marker = html.index("Fragen freischalten")
    start = html.index("<select", marker)
    unlock_select = html[start:html.index("</select>", start)]

    assert f'value="{passend}"' not in unlock_select
    assert f'value="{fremd}"' in unlock_select
