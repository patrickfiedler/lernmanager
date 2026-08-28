"""Extraction reports blocks; render_text() turns them back into the old string.

Every artifact grade so far was produced from the flat string the extractors
used to return. If render_text() drifts from that string, every rubric silently
re-calibrates, so these tests pin it against the real MBI templates rather than
against something hand-written.

The blocks themselves carry what the flat string threw away: whether a line was
a heading, a list item, a table cell or a speaker note, and which slide it was
on. That is what the gate checks in step 3 will read.
"""
import pytest

from artifact_processor import (
    block,
    extract_artifact,
    extract_artifact_blocks,
    extract_docx_blocks,
    extract_odp_blocks,
    extract_odt_blocks,
    extract_pptx_blocks,
    render_text,
)

from tests.test_artifact_extraction import make_docx, make_odt, read_fixture


def kinds(blocks):
    return [(b['kind'], b['text']) for b in blocks]


# --- render_text() reproduces the string the LLM has always been given ---

def test_render_text_of_a_document_joins_lines_and_keeps_heading_markers():
    blocks = [
        block("Startklar", 'body', 'heading', level=1),
        block("Name: ___", 'body', 'paragraph'),
        block("Keine Getränke am PC.", 'body', 'list-item'),
        block("Unterpunkt", 'body', 'heading', level=3),
    ]

    assert render_text(blocks) == (
        "# Startklar\n"
        "Name: ___\n"
        "Keine Getränke am PC.\n"
        "### Unterpunkt"
    )


def test_render_text_of_a_presentation_opens_each_slide_with_its_marker():
    blocks = [
        block("Erste-Hilfe-Station", 'slide', 'title', index=1),
        block("Name: ___", 'slide', 'paragraph', index=1),
        block("Anmelden", 'slide', 'title', index=2),
    ]

    assert render_text(blocks) == (
        "[Folie 1]\n"
        "Erste-Hilfe-Station\n"
        "Name: ___\n"
        "\n"
        "[Folie 2]\n"
        "Anmelden"
    )


def test_render_text_skips_slides_that_produced_no_blocks():
    # A slide with only a picture on it contributes nothing, and the old
    # extractor emitted no "[Folie 2]" heading for it either.
    blocks = [
        block("Erste Folie", 'slide', 'title', index=1),
        block("Dritte Folie", 'slide', 'title', index=3),
    ]

    assert render_text(blocks) == "[Folie 1]\nErste Folie\n\n[Folie 3]\nDritte Folie"


def test_render_text_of_nothing_is_the_empty_string():
    assert render_text([]) == ""


def test_render_text_reproduces_the_real_document_extraction():
    text = render_text(extract_docx_blocks(read_fixture("01_Startklar_Vorlage.docx")))

    assert text.startswith("# Startklar\nName: ______________________    Klasse:")
    assert "Keine Getränke am PC." in text
    assert len(text.split()) == 111


def test_render_text_reproduces_the_real_presentation_extraction():
    text = render_text(extract_pptx_blocks(read_fixture("01_Karten_Vorlage.pptx")))

    assert text.startswith("[Folie 1]\nErste-Hilfe-Station\nfür meine Klasse\nName: ___\n\n[Folie 2]\n")
    assert text.endswith("Schritt 4: Um den Stick sicher zu entfernen: ___.")
    assert len(text.split()) == 141


def test_pptx_and_odp_of_the_same_template_extract_the_same_text():
    pptx = extract_artifact(read_fixture("01_Karten_Vorlage.pptx"), "x.pptx")
    odp = extract_artifact(read_fixture("01_Karten_Vorlage.odp"), "x.odp")

    assert odp == pptx


# --- what the blocks carry that the string could not ---

def test_odt_tags_list_items_and_table_cells():
    blocks = extract_odt_blocks(make_odt(
        '<text:p>Fließtext</text:p>'
        '<text:list><text:list-item><text:p>Regel</text:p></text:list-item></text:list>'
        '<table:table><table:table-row><table:table-cell>'
        '<text:p>Zelle</text:p>'
        '</table:table-cell></table:table-row></table:table>'
    ))

    assert kinds(blocks) == [
        ('paragraph', 'Fließtext'),
        ('list-item', 'Regel'),
        ('table-cell', 'Zelle'),
    ]


def test_docx_tags_list_items_and_table_cells():
    blocks = extract_docx_blocks(make_docx(
        '<w:p><w:r><w:t>Fließtext</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr>'
        '<w:r><w:t>Regel</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Zelle</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    ))

    assert kinds(blocks) == [
        ('paragraph', 'Fließtext'),
        ('list-item', 'Regel'),
        ('table-cell', 'Zelle'),
    ]


def test_headings_carry_their_level():
    blocks = extract_odt_blocks(make_odt('<text:h text:outline-level="3">Regeln</text:h>'))

    assert blocks == [{'text': 'Regeln', 'region': 'body', 'kind': 'heading', 'level': 3}]


def test_document_blocks_are_all_body_region():
    blocks = extract_docx_blocks(read_fixture("01_Startklar_Vorlage.docx"))

    assert {b['region'] for b in blocks} == {'body'}


def test_slide_blocks_carry_their_slide_number():
    blocks = extract_pptx_blocks(read_fixture("01_Karten_Vorlage.pptx"))

    assert {b['region'] for b in blocks} == {'slide'}
    assert sorted({b['index'] for b in blocks}) == [1, 2, 3, 4, 5]


def test_the_slide_title_placeholder_is_tagged_as_a_title():
    blocks = extract_pptx_blocks(read_fixture("01_Karten_Vorlage.pptx"))
    titles = [b['text'] for b in blocks if b['kind'] == 'title']

    assert "Erste-Hilfe-Station" in titles
    assert "Anmelden" in titles
    # Slide 1 has its whole content typed into the title placeholder -- kind
    # records the placeholder it came from, it does not judge the text.
    assert "Name: ___" in titles


def test_odp_speaker_notes_are_tagged_as_notes_not_slide_text():
    _NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
           'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"')
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('content.xml',
                   f'<office:document-content {_NS}><office:body><office:presentation>'
                   '<draw:page>'
                   '<draw:frame presentation:class="title"><text:p>Anmelden</text:p></draw:frame>'
                   '<draw:frame><text:p>Auf der Folie</text:p></draw:frame>'
                   '<presentation:notes><draw:frame><text:p>Nur für mich</text:p></draw:frame>'
                   '</presentation:notes>'
                   '</draw:page></office:presentation></office:body></office:document-content>')
    blocks = extract_odp_blocks(buf.getvalue())

    assert [(b['region'], b['kind'], b['text']) for b in blocks] == [
        ('slide', 'title', 'Anmelden'),
        ('slide', 'paragraph', 'Auf der Folie'),
        ('notes', 'paragraph', 'Nur für mich'),
    ]


def test_scratch_projects_come_back_as_one_block():
    import io, json, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('project.json', json.dumps({'targets': [{'isStage': True, 'blocks': {}}]}))

    blocks = extract_artifact_blocks(buf.getvalue(), "spiel.sb3")

    assert len(blocks) == 1
    assert blocks[0]['region'] == 'body'


def test_unknown_format_is_rejected():
    with pytest.raises(ValueError):
        extract_artifact_blocks(b'', "notizen.txt")
