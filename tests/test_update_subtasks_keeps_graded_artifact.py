"""Saving the admin Aufgaben form must not wipe graded_artifact_json: the form
has no field for it (set by import only), so update_subtasks keeps the stored value."""
import models


def test_admin_save_keeps_graded_artifact(as_admin):
    task_id = models.create_task('5 - Test', 'x', '', 'MBI', '5', 'pflicht')
    models.create_subtask(task_id, '### Eins', reihenfolge=0, graded_artifact_json='{"keyword": "deckblatt"}')
    resp = as_admin.post(f'/admin/thema/{task_id}/aufgaben', data={'subtasks[]': ['### Eins geändert']})
    assert resp.status_code == 302
    [sub] = models.get_subtasks(task_id)
    assert sub['beschreibung'] == '### Eins geändert'
    assert sub['graded_artifact_json'] == '{"keyword": "deckblatt"}'


def test_explicit_list_still_sets_value(db):
    task_id = models.create_task('5 - Test', 'x', '', 'MBI', '5', 'pflicht')
    models.create_subtask(task_id, '### Eins', reihenfolge=0, graded_artifact_json='{"keyword": "alt"}')
    models.update_subtasks(task_id, ['### Eins'], graded_artifact_json_list=[''])
    assert models.get_subtasks(task_id)[0]['graded_artifact_json'] is None
