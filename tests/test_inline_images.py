"""Images embedded in Aufgabe texts: ![alt](material:<datei>).

Requested by chemie (docs/shared/requests/2026-08-26-chemie-inline-images-in-task-checkpoint-text.md):
a hook image has to be seen while reading, not behind a download button.
"""
import pytest
from flask import session

import import_task
import models
from app import markdown_filter

PNG_MAT = {'id': 7, 'typ': 'datei', 'pfad': 'modul_03/kaeltepack.png', 'school_only': 0}
PDF_MAT = {'id': 8, 'typ': 'datei', 'pfad': 'modul_03/anleitung.pdf', 'school_only': 0}
LOCKED_MAT = {'id': 9, 'typ': 'datei', 'pfad': 'modul_03/lehrbuch.jpg', 'school_only': 1}
MATERIALS = [PNG_MAT, PDF_MAT, LOCKED_MAT]


def render(app, text, materials=MATERIALS, admin=False):
    with app.test_request_context(environ_base={'REMOTE_ADDR': '127.0.0.1'}):
        if admin:
            session['admin_id'] = 1
        return str(markdown_filter(text, materials))


def test_material_reference_becomes_embedded_download_url(app):
    html = render(app, "![Kältepack](material:kaeltepack.png)")
    assert '<img' in html
    assert 'src="/material/7/download?eingebettet=1"' in html
    assert 'alt="Kältepack"' in html


def test_image_under_a_step_stays_inside_that_step(app):
    html = render(app, "📋 Aufgabe:\n1. Sieh dir das Foto an.\n   ![Foto](material:kaeltepack.png)\n2. Weiter.")
    first_item = html.split('<li>')[1].split('</li>')[0]
    assert '<img' in first_item
    assert html.count('<ol>') == 1


def test_image_in_table_cell(app):
    html = render(app, "| Stoff | Gefahr |\n|---|---|\n| NaOH | ![ätzend](material:kaeltepack.png) |")
    assert '<td><img' in html


def test_text_without_images_is_unchanged(app):
    text = "### Titel\n🎯 Ziel: etwas\n1. Schritt"
    assert render(app, text) == render(app, text, materials=None)


@pytest.mark.parametrize('ref', ['fehlt.png', 'anleitung.pdf'])
def test_bad_reference_shows_alt_to_student_warning_to_admin(app, ref):
    student = render(app, f"![Beschreibung]({'material:' + ref})")
    assert '<img' not in student
    assert 'Beschreibung' in student
    assert '⚠️' not in student

    admin = render(app, f"![Beschreibung]({'material:' + ref})", admin=True)
    assert 'md-image-problem' in admin
    assert ref in admin


def test_school_only_image_outside_network_shows_lock(app):
    models.set_setting('network_gate_ip_ranges', '10.0.0.0/8')
    html = render(app, "![Seite 12](material:lehrbuch.jpg)")
    assert '<img' not in html
    assert '🔒' in html and 'Seite 12' in html


def test_school_only_image_inside_network_is_shown(app):
    models.set_setting('network_gate_ip_ranges', '127.0.0.0/8')
    html = render(app, "![Seite 12](material:lehrbuch.jpg)")
    assert 'src="/material/9/download?eingebettet=1"' in html


@pytest.mark.parametrize('src', [
    'https://example.com/a.png',
    'http://example.com/a.png',
    '//example.com/a.png',
    'HTTPS://example.com/a.png',
    'data:image/png;base64,AAAA',
    'javascript:alert(1)',
    '/\\example.com/a.png',
    'MATERIAL:kaeltepack.png',
])
def test_foreign_sources_are_not_loaded(app, src):
    html = render(app, f"![extern]({src})")
    assert '<img' not in html
    assert 'extern' in html


def test_local_static_path_still_allowed(app):
    html = render(app, "![Logo](/static/icons/logo.png)")
    assert 'src="/static/icons/logo.png"' in html


def _bundle(beschreibung, materials):
    return {'task': {
        'name': 'T', 'beschreibung': 'x', 'fach': 'Chemie', 'stufe': '11/12',
        'subtasks': [{'beschreibung': beschreibung, 'path': 'wanderweg'}],
        'materials': materials,
    }}


def test_import_accepts_reference_to_image_material():
    data = _bundle("![Foto](material:foto.jpg)",
                   [{'typ': 'datei', 'pfad': 'foto.jpg', 'subtask_indices': [0]}])
    assert import_task.validate_task_structure(data)


@pytest.mark.parametrize('materials', [
    [],
    [{'typ': 'datei', 'pfad': 'foto.pdf', 'subtask_indices': [0]}],
    [{'typ': 'link', 'pfad': 'https://example.com/foto.jpg', 'subtask_indices': [0]}],
])
def test_import_rejects_reference_without_matching_image(materials):
    with pytest.raises(import_task.ValidationError, match='material:foto.jpg'):
        import_task.validate_task_structure(_bundle("![Foto](material:foto.jpg)", materials))
