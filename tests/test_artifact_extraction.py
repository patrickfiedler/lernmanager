"""Extraction must see the same content in .docx and .odt.

Both formats are hand-parsed from their ZIP+XML (no python-docx, no odfdo), so
the two code paths drift independently. They did: extract_odt() walked only the
direct children of <office:text>, and ODF puts list content two levels down
(text:list > text:list-item > text:p) and table content four. MBI's own
Startklar template measured 111 words as .docx and 52 as .odt -- every rule line
of the class lost, which silently broke min_words and required_headings for the
cohorts working in LibreOffice.

The fixtures are MBI's real, unmodified templates. They contain no student data.
"""
import io
import zipfile
from pathlib import Path

import pytest

from artifact_processor import extract_docx, extract_odt

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"

_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_ODT_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"'
)


def _zip_with(name: str, xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(name, xml)
    return buf.getvalue()


def make_docx(body_xml: str) -> bytes:
    return _zip_with('word/document.xml',
                     f'<w:document xmlns:w="{_W}"><w:body>{body_xml}</w:body></w:document>')


def make_odt(body_xml: str) -> bytes:
    return _zip_with('content.xml',
                     f'<office:document-content {_ODT_NS}>'
                     f'<office:body><office:text>{body_xml}</office:text></office:body>'
                     f'</office:document-content>')


def read_fixture(name: str) -> bytes:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"fixture missing: {path}")
    return path.read_bytes()


# --- the regression that started this: .docx and .odt must agree ---

def test_docx_and_odt_of_the_same_template_extract_the_same_text():
    docx = extract_docx(read_fixture("01_Startklar_Vorlage.docx"))
    odt = extract_odt(read_fixture("01_Startklar_Vorlage.odt"))

    assert odt == docx


def test_odt_extracts_the_rule_lines_that_live_in_lists():
    odt = extract_odt(read_fixture("01_Startklar_Vorlage.odt"))

    for rule in ["Keine Getränke am PC.",
                 "Kein Essen am PC.",
                 "Frag die Lehrperson."]:
        assert rule in odt


def test_odt_word_count_matches_docx_on_the_real_template():
    docx_words = len(extract_docx(read_fixture("01_Startklar_Vorlage.docx")).split())
    odt_words = len(extract_odt(read_fixture("01_Startklar_Vorlage.odt")).split())

    assert odt_words == docx_words == 111


# --- nesting: lists and tables ---

def test_odt_reads_nested_list_items():
    odt = extract_odt(make_odt(
        '<text:list><text:list-item><text:p>Erste Regel</text:p></text:list-item>'
        '<text:list-item><text:list>'  # a sub-list, one level deeper
        '<text:list-item><text:p>Unterpunkt</text:p></text:list-item>'
        '</text:list></text:list-item></text:list>'
    ))

    assert odt.splitlines() == ["Erste Regel", "Unterpunkt"]


def test_odt_reads_table_cells():
    odt = extract_odt(make_odt(
        '<table:table><table:table-row>'
        '<table:table-cell><text:p>Regel</text:p></table:table-cell>'
        '<table:table-cell><text:p>Begründung</text:p></table:table-cell>'
        '</table:table-row></table:table>'
    ))

    assert odt.splitlines() == ["Regel", "Begründung"]


def test_odt_reads_headings_nested_inside_a_list():
    odt = extract_odt(make_odt(
        '<text:list><text:list-item>'
        '<text:h text:outline-level="2">Fachraumregeln</text:h>'
        '</text:list-item></text:list>'
    ))

    assert odt.splitlines() == ["## Fachraumregeln"]


# --- the "Titel" paragraph style counts as a heading in both formats ---

def test_docx_title_style_is_a_heading():
    docx = extract_docx(make_docx(
        '<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Meine Startkarte</w:t></w:r></w:p>'
    ))

    assert docx == "# Meine Startkarte"


def test_docx_german_titel_style_is_a_heading():
    docx = extract_docx(make_docx(
        '<w:p><w:pPr><w:pStyle w:val="Titel"/></w:pPr><w:r><w:t>Meine Startkarte</w:t></w:r></w:p>'
    ))

    assert docx == "# Meine Startkarte"


def test_odt_title_style_is_a_heading():
    # LibreOffice's "Titel" writes a styled paragraph, not a text:h element.
    odt = extract_odt(make_odt(
        '<text:p text:style-name="Title">Meine Startkarte</text:p>'
    ))

    assert odt == "# Meine Startkarte"


def test_odt_ordinary_paragraph_is_not_a_heading():
    odt = extract_odt(make_odt('<text:p text:style-name="Standard">Fließtext</text:p>'))

    assert odt == "Fließtext"


# --- whitespace: ODF encodes runs of spaces as an element ---

def test_odt_expands_repeated_spaces():
    # <text:s text:c="3"/> is three spaces; without it the fill-in line
    # "Name: ____   Klasse: ____" collapses and stops matching its .docx twin.
    odt = extract_odt(make_odt('<text:p>Name:<text:s text:c="3"/>Klasse:</text:p>'))

    assert odt == "Name:   Klasse:"


def test_odt_expands_tabs():
    odt = extract_odt(make_odt('<text:p>Name:<text:tab/>Klasse:</text:p>'))

    assert odt == "Name:\tKlasse:"
