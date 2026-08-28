"""min_added_words: how much of the artifact is the student's own.

A student could upload the shipped template untouched and the gate reported
"Abgabe sieht vollständig aus ✓" -- every heading is present and min_words
passes on the template's own 111 words. The baseline needs no new storage: the
template is already a material row of the same topic, named by
template_material.

Compared as a set difference over block texts, not by subtracting word counts,
so deleting half the template and adding nothing is caught too.
"""
from artifact_checker import _check_document, check_gate
from import_task import _validate_artifact_gate

from tests.test_artifact_extraction import make_docx, read_fixture

TEMPLATE = read_fixture("01_Startklar_Vorlage.docx")
GATE = {'format': ['.docx', '.odt'], 'min_added_words': 20,
        'template_material': "01_Startklar_Vorlage.docx"}


def loader(name):
    return TEMPLATE if name == "01_Startklar_Vorlage.docx" else None


def test_the_untouched_template_fails_its_own_gate():
    res = check_gate(TEMPLATE, "01_Startklar_Vorlage.docx", GATE, loader)

    assert res['passed'] is False
    assert "Zu wenig eigener Text (0 Wörter ergänzt, erwartet: 20)" in res['details']


def test_a_filled_in_submission_passes():
    filled = TEMPLATE  # baseline
    own = ("Wenn sich niemand an die Regel haelt kann ein Geraet kaputtgehen und "
           "dann kann die ganze Klasse nicht mehr am Computer arbeiten. Ich merke "
           "dass ich Schritt zwei uebersprungen habe wenn ich noch gar nicht in den "
           "Materialien nachgesehen habe.")
    docx = make_docx(f'<w:p><w:r><w:t>{own}</w:t></w:r></w:p>')

    res = _check_document(docx, '.docx', GATE, loader)

    assert res['passed'] is True
    assert any("eigene Wörter ergänzt" in m for m in res['matches'])
    assert filled is TEMPLATE


def test_deleting_the_template_instead_of_filling_it_in_does_not_pass():
    # A count-based check would see "fewer words than the template" and could be
    # satisfied by any long paste; the set difference asks what is actually new.
    stripped = make_docx('<w:p><w:r><w:t>Startklar</w:t></w:r></w:p>')

    res = _check_document(stripped, '.docx', GATE, loader)

    assert res['passed'] is False


def test_an_odt_submission_is_compared_against_the_docx_template():
    # Only true since the ODT list fix -- before it the two formats of the same
    # template differed by 59 words and the diff meant nothing.
    res = _check_document(read_fixture("01_Startklar_Vorlage.odt"), '.odt', GATE, loader)

    assert res['passed'] is False
    assert "Zu wenig eigener Text (0 Wörter ergänzt, erwartet: 20)" in res['details']


def test_a_missing_template_warns_instead_of_failing_the_student():
    res = _check_document(TEMPLATE, '.docx', GATE, lambda name: None)

    assert res['passed'] is True
    assert res['warnings'] == ["Vorlage zum Vergleich nicht gefunden"]


def test_no_loader_at_all_also_fails_soft():
    res = _check_document(TEMPLATE, '.docx', GATE)

    assert res['passed'] is True
    assert res['warnings'] == ["Vorlage zum Vergleich nicht gefunden"]


def test_import_warns_when_the_template_is_not_named():
    _, warning = _validate_artifact_gate(
        {'format': ['.docx'], 'min_added_words': 20}, "Aufgabe 1")

    assert warning is not None and "template_material" in warning


def test_import_accepts_the_pair():
    gate, warning = _validate_artifact_gate(
        {'format': ['.docx'], 'min_added_words': 20,
         'template_material': "01_Startklar_Vorlage.docx"}, "Aufgabe 1")

    assert warning is None and gate['min_added_words'] == 20


# --- the loader that finds the template among the topic's materials ---

def test_the_app_loader_finds_a_registered_template(app, tmp_path, monkeypatch):
    import config as cfg
    import models
    from app import _template_loader

    monkeypatch.setattr(cfg, 'UPLOAD_FOLDER', str(tmp_path))
    (tmp_path / "01_Startklar_Vorlage.docx").write_bytes(TEMPLATE)

    task_id = models.create_task("Startklar", "", "", "MBI", "6", "kern")
    models.create_material(task_id, 'datei', "01_Startklar_Vorlage.docx")

    load = _template_loader(task_id)

    assert load("01_Startklar_Vorlage.docx") == TEMPLATE


def test_the_loader_returns_nothing_for_a_renamed_material(app, tmp_path, monkeypatch):
    import config as cfg
    import models
    from app import _template_loader

    monkeypatch.setattr(cfg, 'UPLOAD_FOLDER', str(tmp_path))
    task_id = models.create_task("Startklar", "", "", "MBI", "6", "kern")
    models.create_material(task_id, 'datei', "02_Andere_Vorlage.docx")

    assert _template_loader(task_id)("01_Startklar_Vorlage.docx") is None
