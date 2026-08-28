"""min_images counts images actually placed, not files sitting in the ZIP.

MBI's 01_Karten_Vorlage.odp ships a 128 KB JPEG referenced only from
META-INF/manifest.xml -- on no slide, in no master. The old check counted ZIP
entries under Pictures/, so an untouched ODP template passed `min_images: 1`
while its .pptx twin, which has no such orphan, failed the same gate.
"""
import io
import zipfile

from artifact_checker import _check_document, _check_presentation
from artifact_processor import extract_docx_blocks, extract_odp_blocks, extract_pptx_blocks

from tests.test_artifact_extraction import make_docx, read_fixture

_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'


def images(blocks):
    return [b for b in blocks if b['kind'] == 'image']


def test_the_orphan_jpeg_in_the_odp_template_is_not_counted():
    odp = read_fixture("01_Karten_Vorlage.odp")

    with zipfile.ZipFile(io.BytesIO(odp)) as z:
        assert [n for n in z.namelist() if n.startswith('Pictures/')], "fixture lost its orphan"
    assert images(extract_odp_blocks(odp)) == []


def test_the_two_presentation_formats_now_agree_on_a_min_images_gate():
    gate = {'format': ['.pptx', '.odp'], 'min_images': 1}

    odp = _check_presentation(read_fixture("01_Karten_Vorlage.odp"), '.odp', gate)
    pptx = _check_presentation(read_fixture("01_Karten_Vorlage.pptx"), '.pptx', gate)

    assert odp['passed'] is False
    assert pptx['passed'] is False


def test_a_placed_picture_counts_and_carries_its_slide_number():
    _NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
           'xmlns:xlink="http://www.w3.org/1999/xlink"')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('content.xml',
                   f'<office:document-content {_NS}><office:body><office:presentation>'
                   '<draw:page><draw:frame><text:p>Folie eins</text:p></draw:frame></draw:page>'
                   '<draw:page><draw:frame>'
                   '<draw:image xlink:href="Pictures/foto.jpg"/></draw:frame></draw:page>'
                   '</office:presentation></office:body></office:document-content>')

    placed = images(extract_odp_blocks(buf.getvalue()))

    assert len(placed) == 1
    assert placed[0]['index'] == 2


def test_a_docx_picture_is_counted():
    docx = make_docx(
        '<w:p><w:r><w:drawing>'
        f'<a:blip xmlns:a="{_A}" r:embed="rId4" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        '</w:drawing></w:r></w:p>'
    )

    res = _check_document(docx, '.docx', {'min_images': 1})

    assert len(images(extract_docx_blocks(docx))) == 1
    assert res['passed'] is True


def test_a_document_without_pictures_fails_a_min_images_gate():
    res = _check_document(read_fixture("01_Startklar_Vorlage.docx"), '.docx', {'min_images': 1})

    assert res['passed'] is False
    assert "Zu wenig Bilder (0, erwartet: 1)" in res['details']


def test_image_blocks_never_reach_the_text_the_llm_reads():
    from artifact_processor import extract_artifact

    text = extract_artifact(read_fixture("01_Karten_Vorlage.pptx"), "x.pptx")

    assert "\n\n\n" not in text
    assert len(text.split()) == 141
