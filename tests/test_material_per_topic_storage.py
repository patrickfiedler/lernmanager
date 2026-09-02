"""Regression tests: material files are stored per topic, not in a flat namespace.

The point is a Seilbahn twin. It is meant to be invisible in the classroom --
same task title, same keyword, near-identical content -- so a Seilbahn student's
screen doesn't mark them out to a neighbour. In a flat namespace the twin could
not ship `01_Startklar_Vorlage.docx` alongside the regular unit's file of the
same name: the second import overwrote the first, and both cohorts then got the
wrong content. Requested by MBI, docs/shared/lernmanager/inbox.md.
"""
import io
import zipfile

import config
import models
import import_task
from utils import material_pfad, material_filename


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf


def _bundle(task_json, files):
    import json
    return _zip({'task.json': json.dumps(task_json, ensure_ascii=False), **files})


def _task(name, unit_slug, material_name, path='bergweg'):
    return {'task': {
        'name': name, 'beschreibung': '', 'lernziel': '', 'fach': 'MBI',
        'stufe': '6', 'kategorie': 'pflicht', 'unit_slug': unit_slug,
        'subtasks': [{'titel': 'A1', 'beschreibung': 'x', 'reihenfolge': 1, 'path': path}],
        'materials': [{'typ': 'datei', 'pfad': material_name, 'beschreibung': ''}],
    }}


# --- the naming rule itself -------------------------------------------------

def test_unit_slug_is_the_folder_when_present():
    assert material_pfad(40, 'x.docx', 'kl6_startklar') == 'kl6_startklar/x.docx'


def test_falls_back_to_task_id_without_unit_slug():
    assert material_pfad(42, 'x.docx') == 'thema-42/x.docx'


def test_fallback_can_never_collide_with_a_unit_slug_folder():
    """unit_slug is restricted to ^[a-z0-9_]+$, which forbids the dash, so no
    slug can ever spell 'thema-<id>'. That is what makes one rule safe."""
    assert material_pfad(42, 'x.docx', 'thema-7') == 'thema-42/x.docx'


def test_reserved_folders_are_not_taken_over_by_a_slug():
    assert material_pfad(42, 'x.docx', 'artefakte') == 'thema-42/x.docx'
    assert material_pfad(42, 'x.docx', 'grading') == 'thema-42/x.docx'


def test_zip_entry_names_are_reduced_to_a_basename():
    assert material_pfad(42, '../../etc/passwd') == 'thema-42/passwd'
    assert material_pfad(42, '') is None


# --- the actual bug ---------------------------------------------------------

def test_twin_topics_may_ship_the_same_filename(db, tmp_path):
    """The regression this whole change exists for."""
    config.UPLOAD_FOLDER = str(tmp_path / 'uploads')
    (tmp_path / 'uploads').mkdir()
    shared_name = '01_Startklar_Vorlage.docx'

    # Same task title on both, as the design intends -- check_duplicate already
    # exempts a Seilbahn twin, so only the storage layer was in the way.
    for slug, body, path in [('kl6_startklar', b'regular', 'bergweg'),
                             ('kl6_startklar_seilbahn', b'seilbahn', 'seilbahn')]:
        data = _task('1 - Startklar im Fachraum', slug, shared_name, path=path)
        zip_path = tmp_path / f'{slug}.zip'
        zip_path.write_bytes(_bundle(data, {shared_name: body}).read())
        task_id = import_task.import_task(data)
        task = models.get_task(task_id)
        import_task.extract_zip_materials(str(zip_path), data, task_id=task_id,
                                          unit_slug=task['unit_slug'])

    regular = tmp_path / 'uploads' / 'kl6_startklar' / shared_name
    seilbahn = tmp_path / 'uploads' / 'kl6_startklar_seilbahn' / shared_name
    assert regular.read_bytes() == b'regular'
    assert seilbahn.read_bytes() == b'seilbahn'


def test_export_ships_bare_filenames_so_a_reimport_lands_in_its_own_folder(db, tmp_path):
    """Storage is namespaced; the exchange format is not. If export leaked the
    folder into the JSON/ZIP, a re-import would nest it (kl6_startklar/kl6_.../x)
    and MBI's bundles would stop matching."""
    config.UPLOAD_FOLDER = str(tmp_path / 'uploads')
    (tmp_path / 'uploads').mkdir()
    data = _task('T', 'kl6_startklar', 'vorlage.docx')
    task_id = import_task.import_task(data)

    stored = models.get_materials(task_id)[0]['pfad']
    assert stored == 'kl6_startklar/vorlage.docx'

    exported = models.export_task_to_dict(task_id)
    assert exported['materials'][0]['pfad'] == 'vorlage.docx'


def test_overwrite_import_removes_a_file_the_new_version_dropped(db, tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path / 'uploads')
    (tmp_path / 'uploads').mkdir()
    data = _task('T', 'kl6_startklar', 'alt.pdf')
    zip_path = tmp_path / 'a.zip'
    zip_path.write_bytes(_bundle(data, {'alt.pdf': b'old'}).read())
    task_id = import_task.import_task(data)
    import_task.extract_zip_materials(str(zip_path), data, task_id=task_id,
                                      unit_slug='kl6_startklar')
    old_file = tmp_path / 'uploads' / 'kl6_startklar' / 'alt.pdf'
    assert old_file.is_file()

    warnings = []
    neu = _task('T', 'kl6_startklar', 'neu.pdf')
    import_task.overwrite_task_from_import(task_id, neu, warnings=warnings)

    assert not old_file.exists()
    assert any('alt.pdf' in w for w in warnings), warnings


def test_cleanup_leaves_legacy_flat_files_alone(db, tmp_path):
    """A pfad with no folder predates this change and may still be shared with
    another topic. Not ours to delete -- the migration decides its fate."""
    config.UPLOAD_FOLDER = str(tmp_path / 'uploads')
    (tmp_path / 'uploads').mkdir()
    legacy = tmp_path / 'uploads' / 'geteilt.pdf'
    legacy.write_bytes(b'shared')

    task_id = models.create_task('T', '', '', 'MBI', '6', 'pflicht')
    models.create_material(task_id, 'datei', 'geteilt.pdf', '')
    import_task.overwrite_task_from_import(task_id, _task('T', None, 'neu.pdf'))

    assert legacy.is_file()


def test_cleanup_never_touches_student_artifacts(db, tmp_path):
    config.UPLOAD_FOLDER = str(tmp_path / 'uploads')
    artefakte = tmp_path / 'uploads' / 'artefakte'
    artefakte.mkdir(parents=True)
    abgabe = artefakte / 'abgabe.docx'
    abgabe.write_bytes(b'student work')

    removed = import_task._prune_orphaned_files(['artefakte/abgabe.docx'])

    assert removed == []
    assert abgabe.is_file()


def test_student_sees_the_bare_filename_not_the_folder():
    assert material_filename('kl6_startklar/01_Startklar_Vorlage.docx') == '01_Startklar_Vorlage.docx'
    assert material_filename('alt.pdf') == 'alt.pdf'
