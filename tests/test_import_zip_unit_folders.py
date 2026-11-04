"""Combined zip (regular topic + Seilbahn twin): same filename, different file.

MBI request 2026-10-28 (docs/shared/requests/2026-10-28-mbi-kombi-zip-dateien-je-thema-ordner.md):
an entry `<unit_slug>/<pfad>` wins over a bare `<pfad>`, the stored pfad stays bare.
"""
import io
import json
import re
import zipfile

import config
import models
from import_task import zip_entry_for

def _docx(text):
    """Minimal docx that passes content sniffing; text makes the bytes differ."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('word/document.xml', f'<w:document xmlns:w="x">{text}</w:document>')
        zf.writestr('[Content_Types].xml', '<x/>')
    return buf.getvalue()


NAME = '01_Startklar_Vorlage.docx'
DOCX = _docx('regulär')
DOCX_SEILBAHN = _docx('seilbahn')


def _topic(name, slug, path):
    return {'name': name, 'fach': 'MBI', 'stufe': '6', 'beschreibung': 'x',
            'unit_slug': slug,
            'subtasks': [{'beschreibung': '### A', 'path': path}],
            'materials': [{'typ': 'datei', 'pfad': NAME, 'beschreibung': 'v'}]}


def test_folder_entry_wins_bare_name_is_fallback():
    names = {NAME, f'kl6_startklar/{NAME}'}
    assert zip_entry_for(names, NAME, 'kl6_startklar') == f'kl6_startklar/{NAME}'
    assert zip_entry_for(names, NAME, 'andere_einheit') == NAME
    assert zip_entry_for(names, NAME) == NAME
    assert zip_entry_for(set(), NAME, 'kl6_startklar') is None


def test_combined_zip_gives_each_topic_its_own_file(as_admin, app, tmp_path):
    app.config['WTF_CSRF_ENABLED'] = False
    config.UPLOAD_FOLDER = str(tmp_path / 'uploads')
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER

    data = {'tasks': [_topic('Startklar', 'kl6_startklar', 'bergweg'),
                      _topic('Startklar leicht', 'seilbahn_kl6_startklar', 'seilbahn')]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('task.json', json.dumps(data))
        zf.writestr(f'kl6_startklar/{NAME}', DOCX)
        zf.writestr(f'seilbahn_kl6_startklar/{NAME}', DOCX_SEILBAHN)
    buf.seek(0)

    r = as_admin.post('/admin/themen/import',
                      data={'action': 'preview', 'json_file': (buf, 'kombi.zip')},
                      content_type='multipart/form-data')
    body = r.get_data(as_text=True)
    assert 'Fehlende Dateien' not in body
    tmp_id = re.search(r'name="zip_tmp_id" value="([^"]+)"', body).group(1)

    as_admin.post('/admin/themen/import', data={
        'action': 'confirm', 'json_data': json.dumps(data), 'zip_tmp_id': tmp_id,
        'action_0': 'new', 'action_1': 'new'})

    up = tmp_path / 'uploads'
    assert (up / 'kl6_startklar' / NAME).read_bytes() == DOCX
    assert (up / 'seilbahn_kl6_startklar' / NAME).read_bytes() == DOCX_SEILBAHN
    stored = models.get_materials(models.get_task_by_unit_slug('kl6_startklar')['id'])
    assert stored[0]['pfad'] == f'kl6_startklar/{NAME}'  # no doubled folder
