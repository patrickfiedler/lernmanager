"""Regression tests for the Fork/Choice Artifact Model (branching subtasks).

Design: docs/shared/lernmanager/fork-choice-artifact-model.md

Covers the model-layer mechanism: get_visible_subtasks_for_student() excludes
unresolved fork_group subtasks entirely (position-indexing stays intact for
every route built on it); once a branch is chosen, only that branch's
subtasks appear, siblings dropped or kept as Zusatz depending on
fork_required; check_task_completion() refuses to complete while a fork is
still pending.
"""
import models


def _setup_forked_task():
    """Task: base1 -> fork(group 'g1': branch a=[a1,a2], branch b=[b1]) -> after1."""
    student_id = models.create_student("Test", "Schüler", "testschueler", "pw123")
    klasse_id = models.create_klasse("Testklasse")
    models.add_student_to_klasse(student_id, klasse_id)
    task_id = models.create_task("Testthema", "", "", "MBI", "5", "")

    base1 = models.create_subtask(task_id, "Basis 1", reihenfolge=1)
    a1 = models.create_subtask(task_id, "Branch A - 1", reihenfolge=2)
    a2 = models.create_subtask(task_id, "Branch A - 2", reihenfolge=3)
    b1 = models.create_subtask(task_id, "Branch B - 1", reihenfolge=2)
    after1 = models.create_subtask(task_id, "Nach dem Fork", reihenfolge=4)

    with models.db_session() as conn:
        conn.execute(
            "UPDATE subtask SET fork_group='g1', fork_branch='a', fork_branch_label='Branch A' WHERE id=?",
            (a1,)
        )
        conn.execute("UPDATE subtask SET fork_group='g1', fork_branch='a' WHERE id=?", (a2,))
        conn.execute(
            "UPDATE subtask SET fork_group='g1', fork_branch='b', fork_branch_label='Branch B' WHERE id=?",
            (b1,)
        )

    models.assign_task_to_student(student_id, klasse_id, task_id)
    with models.db_session() as conn:
        student_task_id = conn.execute(
            "SELECT id FROM student_task WHERE student_id = ? AND task_id = ?",
            (student_id, task_id)
        ).fetchone()['id']

    return {
        'student_id': student_id, 'klasse_id': klasse_id, 'task_id': task_id,
        'student_task_id': student_task_id,
        'base1': base1, 'a1': a1, 'a2': a2, 'b1': b1, 'after1': after1,
    }


def test_pending_fork_excluded_from_visible_list(db):
    ctx = _setup_forked_task()
    visible = models.get_visible_subtasks_for_student(ctx['student_id'], ctx['klasse_id'], ctx['task_id'])
    visible_ids = {s['id'] for s in visible}

    assert ctx['base1'] in visible_ids
    assert ctx['after1'] in visible_ids
    assert ctx['a1'] not in visible_ids
    assert ctx['a2'] not in visible_ids
    assert ctx['b1'] not in visible_ids
    # position-indexing stays contiguous: base1 then after1, no gap
    assert len(visible) == 2


def test_pending_fork_group_reported(db):
    ctx = _setup_forked_task()
    pending = models.get_pending_fork_groups(ctx['task_id'], ctx['student_id'])

    assert len(pending) == 1
    assert pending[0]['fork_group'] == 'g1'
    branches = {b['branch']: b['label'] for b in pending[0]['branches']}
    assert branches == {'a': 'Branch A', 'b': 'Branch B'}


def test_chosen_branch_included_sibling_excluded_when_required(db):
    ctx = _setup_forked_task()
    models.set_student_fork_choice(ctx['student_id'], 'g1', 'a')

    visible = models.get_visible_subtasks_for_student(ctx['student_id'], ctx['klasse_id'], ctx['task_id'])
    visible_ids = {s['id'] for s in visible}

    assert {ctx['base1'], ctx['a1'], ctx['a2'], ctx['after1']} == visible_ids
    assert ctx['b1'] not in visible_ids
    assert models.get_pending_fork_groups(ctx['task_id'], ctx['student_id']) == []


def test_enrichment_fork_keeps_sibling_as_zusatz(db):
    ctx = _setup_forked_task()
    with models.db_session() as conn:
        conn.execute("UPDATE subtask SET fork_required=0 WHERE fork_group='g1'")
    models.set_student_fork_choice(ctx['student_id'], 'g1', 'a')

    visible = models.get_visible_subtasks_for_student(ctx['student_id'], ctx['klasse_id'], ctx['task_id'])
    by_id = {s['id']: s for s in visible}

    assert ctx['b1'] in by_id
    assert by_id[ctx['b1']]['required'] is False
    assert by_id[ctx['a1']]['required'] is True


def test_completion_blocked_while_fork_pending(db):
    ctx = _setup_forked_task()
    models.toggle_student_subtask(ctx['student_task_id'], ctx['base1'], True)
    models.toggle_student_subtask(ctx['student_task_id'], ctx['after1'], True)

    assert models.check_task_completion(ctx['student_task_id']) is False


def test_completion_proceeds_once_branch_resolved_and_done(db):
    ctx = _setup_forked_task()
    models.set_student_fork_choice(ctx['student_id'], 'g1', 'a')
    for sid in (ctx['base1'], ctx['a1'], ctx['a2'], ctx['after1']):
        models.toggle_student_subtask(ctx['student_task_id'], sid, True)

    assert models.check_task_completion(ctx['student_task_id']) is True


def test_fork_choice_lock(db):
    ctx = _setup_forked_task()
    models.set_student_fork_choice(ctx['student_id'], 'g1', 'a')
    assert models.is_fork_choice_locked(ctx['student_id'], 'g1', 'a') is False

    models.toggle_student_subtask(ctx['student_task_id'], ctx['a1'], True)
    assert models.is_fork_choice_locked(ctx['student_id'], 'g1', 'a') is True

    # re-pick before lock is a plain upsert, not a duplicate-key error
    models.set_student_fork_choice(ctx['student_id'], 'g1', 'b')
    assert models.get_student_fork_choice(ctx['student_id'], 'g1') == 'b'
