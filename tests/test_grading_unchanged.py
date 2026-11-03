"""An unchanged file already reviewed counts as looked at (Patrick 2026-11-03,
request 2026-11-03-lernmanager-document-block-sha256-...): the new result is set
aside at import, logged as 'unchanged', and undo puts it back in the queue."""
import pytest

import models


@pytest.fixture
def no_download(monkeypatch):
    """Skip the HTTP copy: keep only the identity fields the service sent."""
    monkeypatch.setattr(models, '_copy_grading_document', lambda run_id, job_id, login, doc: (
        {'file': None, 'pages': [], 'sha256': doc.get('sha256'),
         'rubric_version': doc.get('rubric_version')} if doc else None))


def _student(doc):
    return {"student_id": "mueller.anna", "total_score": 2, "max_score": 2,
            "criteria": [{"name": "Folie", "score": 2, "max_score": 2, "review_required": True}],
            "document": doc}


def _run(job_id, task_id, klasse_id, doc):
    run_id = models.create_grading_run(job_id, klasse_id, task_id, "deckblatt", "ollama", None)
    models.import_grading_callback(job_id=job_id, provider="ollama", model="m",
                                   graded_at="2026-11-03T10:00:00Z", students=[_student(doc)])
    return run_id, models.list_grading_results(run_id)[0]


def _settle(result):
    """Teacher looks at it, confirms the always-review criterion, releases."""
    criteria = [dict(c, confirmed=True) for c in result['criteria']]
    models.save_grading_result_review(result['id'], criteria)
    models.release_grading_result(result['id'], None)


DOC = {"sha256": "a" * 64, "rubric_version": "1" * 16}


@pytest.fixture
def first_run(db, no_download):
    klasse_id = models.create_klasse("5a")
    task_id = models.create_task("Deckblatt", "d", "lz", "MBI", "5", "pflicht")
    models.create_student("Mueller", "Anna", "uanna", "pw", netzwerk_id="mueller.anna")
    _, first = _run("job-1", task_id, klasse_id, DOC)
    _settle(first)
    return task_id, klasse_id


def test_same_file_same_rubric_is_set_aside(first_run):
    run_id, second = _run("job-2", *first_run, DOC)
    assert second['status'] == 'discarded'
    assert models.unchanged_result_ids(run_id) == {second['id']}


@pytest.mark.parametrize("doc", [
    {"sha256": "b" * 64, "rubric_version": "1" * 16},   # file changed
    {"sha256": "a" * 64, "rubric_version": "2" * 16},   # rubric changed
    {"sha256": None, "rubric_version": None},           # old service
    None,                                               # no document at all
])
def test_anything_else_goes_to_the_queue(first_run, doc):
    _, second = _run("job-2", *first_run, doc)
    assert second['status'] == 'imported'


def test_unreviewed_earlier_result_does_not_count(db, no_download):
    klasse_id = models.create_klasse("5a")
    task_id = models.create_task("Deckblatt", "d", "lz", "MBI", "5", "pflicht")
    models.create_student("Mueller", "Anna", "uanna", "pw", netzwerk_id="mueller.anna")
    _run("job-1", task_id, klasse_id, DOC)
    _, second = _run("job-2", task_id, klasse_id, DOC)
    assert second['status'] == 'imported'


def test_earlier_run_without_the_fields_never_matches(first_run):
    """Runs from before the service change have no sha256 / rubric_version."""
    assert not models._same_document({'file': 'x'}, DOC)
    assert not models._same_document(None, DOC)


def test_undo_puts_it_back_in_the_queue(first_run):
    run_id, second = _run("job-2", *first_run, DOC)
    log = [e for e in models.list_grading_audit(run_id) if e['action'] == 'unchanged']
    assert len(log) == 1
    models.undo_grading_decisions([log[0]['id']], None)
    assert models.get_grading_result(second['id'])['status'] == 'imported'
    assert models.unchanged_result_ids(run_id) == set()
