"""Headers, footers, and the text box that used to be counted twice.

Only word/document.xml was ever opened, so a name/class field printed into a
header was invisible -- exactly where a forbidden_text check on "______" needs
to look. ODF keeps headers in styles.xml, not content.xml, so both formats
missed them for different reasons.

They are extracted but not rendered: they were never part of the string the LLM
grades, and adding them now would move every min_words and every rubric.
"""
import io
import zipfile

from artifact_checker import _check_document
from artifact_processor import extract_docx_blocks, extract_odt_blocks, render_text

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_ODF = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')

HEADER_LINE = "Name: ______  Klasse: ____"


def docx(body: str, extra: dict = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('word/document.xml',
                   f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        for name, xml in (extra or {}).items():
            z.writestr(name, xml)
    return buf.getvalue()


def docx_with_header() -> bytes:
    return docx('<w:p><w:r><w:t>Fließtext</w:t></w:r></w:p>', {
        'word/header1.xml': f'<w:hdr xmlns:w="{W}"><w:p><w:r>'
                            f'<w:t>{HEADER_LINE}</w:t></w:r></w:p></w:hdr>',
        'word/footer1.xml': f'<w:ftr xmlns:w="{W}"><w:p><w:r>'
                            f'<w:t>Seite 1</w:t></w:r></w:p></w:ftr>',
    })


def odt_with_header() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('content.xml',
                   f'<office:document-content {_ODF}><office:body><office:text>'
                   '<text:p>Fließtext</text:p>'
                   '</office:text></office:body></office:document-content>')
        z.writestr('styles.xml',
                   f'<office:document-styles {_ODF}><office:master-styles>'
                   '<style:master-page>'
                   f'<style:header><text:p>{HEADER_LINE}</text:p></style:header>'
                   '<style:footer><text:p>Seite 1</text:p></style:footer>'
                   '</style:master-page></office:master-styles></office:document-styles>')
    return buf.getvalue()


def regions(blocks):
    return {(b['region'], b['text']) for b in blocks}


def test_docx_header_and_footer_are_extracted():
    assert regions(extract_docx_blocks(docx_with_header())) == {
        ('body', 'Fließtext'), ('header', HEADER_LINE), ('footer', 'Seite 1')}


def test_odt_header_and_footer_are_extracted_from_styles_xml():
    assert regions(extract_odt_blocks(odt_with_header())) == {
        ('body', 'Fließtext'), ('header', HEADER_LINE), ('footer', 'Seite 1')}


def test_header_text_stays_out_of_the_string_the_llm_grades():
    for blocks in (extract_docx_blocks(docx_with_header()), extract_odt_blocks(odt_with_header())):
        assert render_text(blocks) == "Fließtext"


def test_forbidden_text_can_now_look_in_the_header():
    res = _check_document(docx_with_header(), '.docx',
                          {'forbidden_text': [{'text': "______", 'in': 'header'}]})

    assert res['passed'] is False


def test_a_filled_in_header_passes():
    filled = docx('<w:p><w:r><w:t>Fließtext</w:t></w:r></w:p>', {
        'word/header1.xml': f'<w:hdr xmlns:w="{W}"><w:p><w:r>'
                            '<w:t>Name: Mia Berger  Klasse: 6b</w:t></w:r></w:p></w:hdr>'})

    res = _check_document(filled, '.docx', {'forbidden_text': [{'text': "______", 'in': 'header'}]})

    assert res['passed'] is True


def test_a_text_box_is_not_counted_twice():
    # <w:txbxContent> nests whole <w:p> elements inside the outer paragraph, so
    # collecting every <w:t> below the outer one read the box's words twice.
    body = ('<w:p><w:r><w:t>Aussen </w:t></w:r><w:r>'
            '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
            f'<w:txbxContent xmlns:w="{W}"><w:p><w:r><w:t>Im Kasten</w:t></w:r></w:p>'
            '</w:txbxContent></mc:AlternateContent></w:r></w:p>')

    text = render_text(extract_docx_blocks(docx(body)))

    assert text == "Aussen\nIm Kasten"
    assert text.count("Im Kasten") == 1
