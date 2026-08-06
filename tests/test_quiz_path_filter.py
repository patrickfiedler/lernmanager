"""Regression tests for per-question path filtering in topic/subtask quizzes.

is_question_visible_for_path() must be cumulative (wanderweg ⊂ bergweg ⊂
gipfeltour) like is_subtask_required_for_path(), with seilbahn isolated.
Questions without a 'path' key stay visible to everyone (legacy default).
"""
import models


def test_question_without_path_visible_to_all():
    q = {"text": "Was ist ein Pixel?", "options": ["a", "b"], "correct": [0]}
    for path in ["wanderweg", "bergweg", "gipfeltour", "seilbahn"]:
        assert models.is_question_visible_for_path(q, path)


def test_bergweg_question_hidden_from_wanderweg():
    q = {"text": "...", "path": "bergweg"}
    assert not models.is_question_visible_for_path(q, "wanderweg")
    assert models.is_question_visible_for_path(q, "bergweg")
    assert models.is_question_visible_for_path(q, "gipfeltour")


def test_gipfeltour_question_only_for_gipfeltour():
    q = {"text": "...", "path": "gipfeltour"}
    assert not models.is_question_visible_for_path(q, "wanderweg")
    assert not models.is_question_visible_for_path(q, "bergweg")
    assert models.is_question_visible_for_path(q, "gipfeltour")


def test_seilbahn_isolated_from_main_paths():
    seilbahn_q = {"text": "...", "path": "seilbahn"}
    main_q = {"text": "...", "path": "bergweg"}

    assert models.is_question_visible_for_path(seilbahn_q, "seilbahn")
    assert not models.is_question_visible_for_path(seilbahn_q, "wanderweg")
    assert not models.is_question_visible_for_path(seilbahn_q, "gipfeltour")
    assert not models.is_question_visible_for_path(main_q, "seilbahn")


def test_unknown_student_path_falls_back_to_visible():
    q = {"text": "...", "path": "bergweg"}
    assert models.is_question_visible_for_path(q, None)
    assert models.is_question_visible_for_path(q, "")
