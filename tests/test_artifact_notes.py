"""Speaker notes are not slide text.

.pptx extraction never saw the notes pane; .odp swept it up with a blind
`.//text:p` over the whole page. The same deck saved in both formats therefore
produced two different texts, two different word counts and two different
min_chars_per_slide verdicts. Notes are still extracted -- tagged
region: 'notes', so a gate can look in them on purpose -- they just stop
counting as something written on the slide.
"""
import io
import zipfile

from artifact_checker import _check_presentation
from artifact_processor import extract_artifact, extract_odp_blocks, render_text

from tests.test_artifact_extraction import read_fixture

_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
       'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
       'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
       'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"')

SLIDE_TEXT = "Kurz"
NOTES_TEXT = "Hier steht ein langer Vortragstext den niemand auf der Folie sieht"


def odp_with_notes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('content.xml',
                   f'<office:document-content {_NS}><office:body><office:presentation>'
                   '<draw:page>'
                   f'<draw:frame presentation:class="title"><text:p>{SLIDE_TEXT}</text:p></draw:frame>'
                   f'<presentation:notes><draw:frame><text:p>{NOTES_TEXT}</text:p></draw:frame>'
                   '</presentation:notes>'
                   '</draw:page></office:presentation></office:body></office:document-content>')
    return buf.getvalue()


def test_notes_are_extracted_but_not_rendered_as_slide_text():
    blocks = extract_odp_blocks(odp_with_notes())

    assert NOTES_TEXT in [b['text'] for b in blocks if b['region'] == 'notes']
    assert render_text(blocks) == f"[Folie 1]\n{SLIDE_TEXT}"


def test_a_note_does_not_satisfy_min_chars_per_slide():
    res = _check_presentation(odp_with_notes(), '.odp', {'min_chars_per_slide': 20})

    assert res['passed'] is False
    assert "Folie 1 hat zu wenig Text (4 Zeichen, erwartet: 20)" in res['details']


def test_a_gate_can_still_look_inside_the_notes_on_purpose():
    res = _check_presentation(odp_with_notes(), '.odp',
                              {'required_text': [{'text': "langer Vortragstext", 'in': 'notes'}]})

    assert res['passed'] is True


def test_expect_content_in_slides_warns_when_the_text_sits_in_the_notes():
    res = _check_presentation(odp_with_notes(), '.odp', {'expect_content_in': 'slides'})

    assert res['passed'] is True
    assert res['warnings'] == ["Der meiste Text steht nicht auf den Folien"]


def test_both_presentation_formats_answer_the_same_gate_the_same_way():
    gate = {'format': ['.pptx', '.odp'], 'min_slides': 5, 'min_chars_per_slide': 20,
            'required_slide_titles': ["Anmelden", "USB-Stick benutzen"], 'min_images': 1}

    pptx = _check_presentation(read_fixture("01_Karten_Vorlage.pptx"), '.pptx', gate)
    odp = _check_presentation(read_fixture("01_Karten_Vorlage.odp"), '.odp', gate)

    assert pptx['passed'] == odp['passed'] is False  # min_images: neither has one
    assert pptx['details'] == odp['details']
    assert pptx['matches'] == odp['matches']


def test_both_formats_of_the_real_template_still_extract_identical_text():
    pptx = extract_artifact(read_fixture("01_Karten_Vorlage.pptx"), "x.pptx")
    odp = extract_artifact(read_fixture("01_Karten_Vorlage.odp"), "x.odp")

    assert pptx == odp
