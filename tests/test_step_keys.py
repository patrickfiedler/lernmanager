"""Step ticks survive content edits: server-side keys equal the browser's, and a
reworded step hands its tick to its new wording (step_keys.py)."""
import json

import models
import step_keys


def test_key_equals_the_browsers():
    # Stored by real browsers (local DB, 2026-11-28) for these exact texts.
    assert step_keys.step_key('Speichere die Datei.') == '1wum30k'
    assert step_keys.step_key(
        'Erstelle im Ordner MBI einen neuen Ordner mit dem Namen Willkommen.') == '1tp4be5'


def test_step_texts_skip_nested_lists_and_collapse_whitespace():
    html = ('<ol><li>Öffne <b>Word</b>.\n<ul><li>Unterpunkt</li></ul></li>'
            '<li>Speichere&nbsp;die   Datei.</li></ol><ul><li>keine Schritte</li></ul>')
    assert step_keys.step_texts(html) == ['Öffne Word.', 'Speichere die Datei.']


def test_moved_step_keeps_its_tick():
    old = ['Öffne Word.', 'Speichere die Datei.']
    new = ['Speichere die Datei.', 'Neuer Schritt ganz anderer Art.', 'Öffne Word.']
    ticks = [step_keys.step_key('Öffne Word.')]
    assert step_keys.remap_ticks(ticks, old, new) == ticks


def test_reworded_step_hands_on_its_tick():
    old = ['Erstelle eine neue Folie „Meine Antwort“. Beantworte deine Frage in 3-4 Sätzen.']
    new = ['Lies das PDF.', 'Erstelle eine neue Folie mit dem Titel „Meine Antwort“. '
                            'Beantworte deine Frage in 3-4 Sätzen.']
    assert step_keys.remap_ticks([step_keys.step_key(old[0])], old, new) == [step_keys.step_key(new[1])]


def test_false_match_loses_to_the_real_successor():
    """From MBI's history: the USB step is similar to the new "Öffne" step only
    through the shared file name; the old "Öffne" step is more similar and wins."""
    old = ['Kopiere deine Datei 2-mein-computer-pass.pptx auf den USB-Stick.',
           'Öffne deine Datei 2-mein-computer-pass.pptx im Ordner MBI/Willkommen.']
    new = ['Öffne deine Datei 2-mein-computer-pass.pptx.']
    assert step_keys.remap_ticks([step_keys.step_key(old[0])], old, new) == []
    assert step_keys.remap_ticks([step_keys.step_key(old[1])], old, new) == [step_keys.step_key(new[0])]


def test_rewritten_step_drops_its_tick():
    old = ['Schreibe die Überschrift.']
    new = ['Lade die Datei im Lernmanager hoch.']
    assert step_keys.remap_ticks([step_keys.step_key(old[0])], old, new) == []


def test_reimport_carries_ticks(app):
    import app as appmod
    student_id = models.create_student('Alex', 'Schueler', 'steptest', 'pw123')
    task_id = models.create_task('Schrittthema', '', '', 'MBI', '6', 'pflicht')
    old_text = '1. Öffne Word.\n2. Schreibe die Überschrift „Teil 1: Meine Wetterkarte“.\n3. Speichere.'
    subtask_id = models.create_subtask(task_id, old_text, reihenfolge=0)
    ticked = [step_keys.step_key('Öffne Word.'),
              step_keys.step_key('Schreibe die Überschrift „Teil 1: Meine Wetterkarte“.')]
    models.save_step_ticks(student_id, subtask_id, ticked)

    before = appmod._step_texts_by_subtask(task_id)
    models.update_subtasks_from_import(task_id, [{
        'reihenfolge': 0,
        'beschreibung': '1. Lies S. 17.\n2. Öffne Word.\n'
                        '3. Schreibe fett: „Teil 1: Meine Wetterkarte“ als Überschrift.\n4. Speichere.'}])
    appmod._carry_step_ticks(task_id, before)

    assert models.get_step_ticks(student_id, [subtask_id])[subtask_id] == sorted([
        step_keys.step_key('Öffne Word.'),
        step_keys.step_key('Schreibe fett: „Teil 1: Meine Wetterkarte“ als Überschrift.')])


def test_reimport_with_new_gate_keeps_progress(app):
    """Kl.6 U3 (MBI request 2026-11-27): a re-import that adds a gate per task and
    a quiz question must not reset a finished task, a passed quiz or the topic."""
    student_id = models.create_student('Bea', 'Schueler', 'gatetest', 'pw123')
    klasse_id = models.create_klasse('Gateklasse')
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task('Gatethema', '', '', 'MBI', '6', 'pflicht')
    quiz = {'questions': [{'text': 'F?', 'options': ['a', 'b'], 'correct': [0]}]}
    t0 = models.create_subtask(task_id, 'Einführung', reihenfolge=0, quiz_json=json.dumps(quiz))
    t1 = models.create_subtask(task_id, 'T1', reihenfolge=1)
    models.create_subtask(task_id, 'T2', reihenfolge=2)
    models.assign_task_to_student(student_id, klasse_id, task_id)
    st = models.get_student_task(student_id, klasse_id)
    models.save_quiz_attempt(st['id'], 1, 1, '{}', subtask_id=t0)
    models.toggle_student_subtask(st['id'], t0, True)
    models.toggle_student_subtask(st['id'], t1, True)

    gate = {'format': ['.pptx'], 'min_slides': 3}
    quiz['questions'].insert(1, {'text': 'Neu?', 'options': ['a', 'b'], 'correct': [1]})
    models.update_subtasks_from_import(task_id, [
        {'reihenfolge': 0, 'beschreibung': 'Einführung neu', 'quiz': quiz},
        {'reihenfolge': 1, 'beschreibung': 'T1 neu', 'artifact_gate': gate},
        {'reihenfolge': 2, 'beschreibung': 'T2 neu', 'artifact_gate': gate},
    ])

    done = {s['id']: s['erledigt'] for s in models.get_student_subtask_progress(st['id'])}
    assert done[t0] and done[t1]
    with models.db_session() as conn:
        assert conn.execute('SELECT bestanden FROM quiz_attempt WHERE subtask_id = ?', (t0,)).fetchone()[0] == 1
