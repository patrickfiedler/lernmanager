"""required_text / forbidden_text / expect_content_in / min_words_required.

Replaces required_headings, which could only ever see heading lines because the
checker had a flat string and a '#' prefix to work with. The scoping (`in:` for
region, `kind:` for role) ships with the first version deliberately: MBI authors
against this shape, and changing a content contract after the content exists is
the expensive kind of change.

Two match semantics on purpose -- see _text_present(). forbidden_text needs
substring ("______" sits inside "Name: ______  Klasse: ____"), required_text
inherits required_headings' fuzzy whole-line tolerance.
"""
from artifact_checker import _check_document, _check_presentation, check_gate
from import_task import _validate_artifact_gate

from tests.test_artifact_extraction import make_docx, make_odt, read_fixture

DOC = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Fachraumregeln</w:t></w:r></w:p>'
       '<w:p><w:r><w:t>Name: ______________________    Klasse: __________</w:t></w:r></w:p>'
       '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr>'
       '<w:r><w:t>Keine Getränke am PC.</w:t></w:r></w:p>')


def check_doc(config, body=DOC):
    return _check_document(make_docx(body), '.docx', config)


# --- required_text ---

def test_required_text_finds_a_line_that_is_not_a_heading():
    res = check_doc({'required_text': ["Keine Getränke am PC."]})

    assert res['passed'] is True
    assert 'Text gefunden: „Keine Getränke am PC.“ ✓' in res['matches']


def test_required_text_reports_what_is_missing():
    res = check_doc({'required_text': ["Kein Essen am PC."]})

    assert res['passed'] is False
    assert 'Text fehlt: „Kein Essen am PC.“' in res['details']


def test_required_text_ignores_whitespace_differences():
    res = check_doc({'required_text': ["Keine  Getränke   am PC."]})

    assert res['passed'] is True


def test_required_text_matches_a_string_inside_a_longer_line():
    res = check_doc({'required_text': ["Getränke"]})

    assert res['passed'] is True


def test_body_text_is_matched_exactly_not_fuzzily():
    # "Kein Essen am PC." scores 0.74 against "Keine Getränke am PC.", well over
    # the 0.6 threshold -- fuzzy body matching would pass a check for a rule the
    # student never wrote.
    res = check_doc({'required_text': ["Kein Essen am PC."]})

    assert res['passed'] is False


def test_a_heading_may_be_retyped_slightly_differently():
    # kind: heading keeps required_headings' tolerance. Headings are few and
    # distinct, so fuzziness there does not collide with a sibling line.
    res = check_doc({'required_text': [{'text': "Fachraum-Regeln", 'kind': 'heading'}]})

    assert res['passed'] is True


# --- kind: and in: scoping ---

def test_kind_heading_restricts_the_search_to_headings():
    ok = check_doc({'required_text': [{'text': "Fachraumregeln", 'kind': 'heading'}]})
    # The same words exist as body text elsewhere, but not as a heading.
    missing = check_doc({'required_text': [{'text': "Keine Getränke am PC.", 'kind': 'heading'}]})

    assert ok['passed'] is True
    assert missing['passed'] is False


def test_a_heading_rule_is_reported_as_a_section():
    res = check_doc({'required_text': [{'text': "Klimawandel", 'kind': 'heading'}]})

    assert 'Abschnitt fehlt: „Klimawandel“' in res['details']


def test_kind_list_item_sees_the_content_odt_used_to_drop():
    res = _check_document(make_odt(
        '<text:list><text:list-item><text:p>Keine Kabel umstecken.</text:p>'
        '</text:list-item></text:list>'
    ), '.odt', {'required_text': [{'text': "Keine Kabel umstecken.", 'kind': 'list-item'}]})

    assert res['passed'] is True


def test_in_notes_does_not_match_text_that_is_on_the_slide():
    pptx = read_fixture("01_Karten_Vorlage.pptx")
    on_slide = _check_presentation(pptx, '.pptx', {'required_text': ["Anmelden"]})
    in_notes = _check_presentation(pptx, '.pptx', {'required_text': [{'text': "Anmelden", 'in': 'notes'}]})

    assert on_slide['passed'] is True
    assert in_notes['passed'] is False


def test_text_rules_work_on_presentations_too():
    res = _check_presentation(read_fixture("01_Karten_Vorlage.odp"), '.odp',
                              {'required_text': [{'text': "USB-Stick benutzen", 'in': 'slides'}]})

    assert res['passed'] is True


# --- forbidden_text: the template-placeholder check ---

def test_forbidden_text_catches_a_placeholder_left_in_the_template():
    res = check_doc({'forbidden_text': ["______________________"]})

    assert res['passed'] is False
    assert 'Noch aus der Vorlage übrig: „______________________“' in res['details']


def test_forbidden_text_passes_once_the_student_filled_it_in():
    filled = ('<w:p><w:r><w:t>Name: Mia Berger    Klasse: 6b</w:t></w:r></w:p>')
    res = check_doc({'forbidden_text': ["______________________"]}, body=filled)

    assert res['passed'] is True
    assert '„______________________“ ist ersetzt ✓' in res['matches']


def test_an_untouched_template_fails_its_own_forbidden_text():
    res = check_gate(read_fixture("01_Startklar_Vorlage.docx"), "01_Startklar_Vorlage.docx",
                     {'format': ['.docx'], 'forbidden_text': ["______________________"]})

    assert res['passed'] is False


# --- expect_content_in warns, never fails ---

def test_content_in_the_wrong_region_is_only_a_warning():
    odt = make_odt('<text:p>Ein ganzer Satz mit vielen Wörtern steht hier im Text.</text:p>')
    res = _check_document(odt, '.odt', {'expect_content_in': 'slides'})

    assert res['passed'] is True
    assert res['warnings'] == ["Der meiste Text steht nicht auf den Folien"]


def test_content_in_the_expected_region_warns_about_nothing():
    res = _check_presentation(read_fixture("01_Karten_Vorlage.pptx"), '.pptx',
                              {'expect_content_in': 'slides'})

    assert res['warnings'] == []


# --- min_words_required promotes the warning to a failure ---

def test_min_words_stays_a_warning_by_default():
    res = check_doc({'min_words': 500})

    assert res['passed'] is True
    assert res['warnings'] == ["wenig Text vorhanden"]


def test_min_words_required_turns_it_into_a_failure():
    res = check_doc({'min_words': 500, 'min_words_required': True})

    assert res['passed'] is False
    assert any("Zu wenig Text" in d for d in res['details'])


# --- required_headings is gone, and says so at import time ---

def test_required_headings_is_no_longer_checked():
    res = check_doc({'required_headings': ["Gibt es gar nicht"]})

    assert res['passed'] is True


def test_import_warns_about_required_headings_without_dropping_the_gate():
    gate, warning = _validate_artifact_gate(
        {'format': ['.docx'], 'required_headings': ["Fachraumregeln"]}, "Aufgabe 1")

    assert gate is not None
    assert "required_headings" in warning
    assert "kind: heading" in warning


def test_import_accepts_the_shapes_mbi_authored():
    gate, warning = _validate_artifact_gate({
        'format': ['.docx'],
        'required_text': [{'text': "Fachraumregeln", 'kind': 'heading'}, "Keine Getränke am PC."],
        'forbidden_text': ["______"],
    }, "Aufgabe 1")

    assert warning is None
    assert gate['required_text'][0]['kind'] == 'heading'


def test_import_warns_about_a_malformed_rule():
    _, warning = _validate_artifact_gate(
        {'format': ['.docx'], 'required_text': [{'kind': 'heading'}]}, "Aufgabe 1")

    assert warning is not None and "required_text" in warning
