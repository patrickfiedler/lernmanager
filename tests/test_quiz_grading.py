"""The scoring rule for the ordering and matching question types.

The rule is a contract with two other projects (docs/shared/lernmanager/
task_json_format.md § Bewertung and chemie-data-contract.md § 4a), so these
tests pin the documented numbers, not just "some partial credit happens".
"""
import random

import pytest

import quiz_grading


ORDERING = {
    "type": "ordering",
    "text": "Bring die Schritte in die richtige Reihenfolge.",
    "items": ["Aufgabe lesen", "Material ansehen", "Nachbarn fragen", "Lehrkraft fragen"],
}

MATCHING = {
    "type": "matching",
    "text": "Ordne zu.",
    "pairs": [["Anode", "Oxidation"], ["Kathode", "Reduktion"],
              ["Galvanisch", "Freiwillig"], ["Elektrolytisch", "Erzwungen"]],
    "distractors": ["Neutralisation"],
}


# --- the documented rounding rule -------------------------------------------

@pytest.mark.parametrize("fraction, expected", [
    (1.0, 1.0),
    (0.75, 0.5),      # 3 of 4 -- floored, not rounded up
    (0.5, 0.5),
    (1 / 3, 0.0),     # 1 of 3 earns nothing
    (2 / 3, 0.5),
    (0.0, 0.0),
])
def test_points_are_floored_to_half_points(fraction, expected):
    assert quiz_grading.points_for(fraction) == expected


def test_points_survive_float_representation_noise():
    # 3/5 * 2 is 1.2000000000000002; a naive floor on a value that landed just
    # below an exact boundary would silently drop a point.
    assert quiz_grading.points_for(5 / 5) == 1.0
    assert quiz_grading.points_for(3 / 5) == 0.5


# --- ordering ---------------------------------------------------------------

def test_ordering_full_marks_for_the_authored_order():
    result = quiz_grading.grade(ORDERING, ORDERING["items"])
    assert result["correct"] is True
    assert result["points"] == 1.0


def test_ordering_counts_adjacencies_not_positions():
    # Everything shifted by one: not a single item sits in its authored slot,
    # but two of the three transitions are still right.
    shifted = ["Lehrkraft fragen", "Aufgabe lesen", "Material ansehen", "Nachbarn fragen"]
    result = quiz_grading.grade(ORDERING, shifted)
    assert (result["right"], result["total"]) == (2, 3)
    assert result["correct"] is False
    assert result["points"] == 0.5


def test_ordering_reversed_scores_nothing():
    result = quiz_grading.grade(ORDERING, list(reversed(ORDERING["items"])))
    assert result["right"] == 0
    assert result["points"] == 0.0


def test_ordering_rejects_a_submission_that_is_not_a_permutation():
    # A tampered or stale client payload, not a wrong answer -- scoring its
    # adjacencies would invent a partial credit nobody earned.
    result = quiz_grading.grade(ORDERING, ["Aufgabe lesen", "Erfunden"])
    assert result["correct"] is False
    assert result["points"] == 0.0
    assert "nicht gelesen werden" in result["feedback"]


def test_ordering_of_two_items_is_all_or_nothing():
    q = {"type": "ordering", "text": "x", "items": ["A", "B"]}
    assert quiz_grading.grade(q, ["A", "B"])["points"] == 1.0
    assert quiz_grading.grade(q, ["B", "A"])["points"] == 0.0


# --- matching ---------------------------------------------------------------

def test_matching_full_marks():
    answer = {left: right for left, right in MATCHING["pairs"]}
    result = quiz_grading.grade(MATCHING, answer)
    assert result["correct"] is True
    assert result["points"] == 1.0


def test_matching_three_of_four_scores_half_a_point():
    answer = {left: right for left, right in MATCHING["pairs"]}
    answer["Elektrolytisch"] = "Neutralisation"      # a distractor
    result = quiz_grading.grade(MATCHING, answer)
    assert (result["right"], result["total"]) == (3, 4)
    assert result["correct"] is False
    assert result["points"] == 0.5
    assert result["feedback"] == "3 von 4 Paaren richtig zugeordnet."


def test_matching_counts_an_unanswered_row_as_wrong():
    result = quiz_grading.grade(MATCHING, {"Anode": "Oxidation"})
    assert (result["right"], result["total"]) == (1, 4)
    assert result["points"] == 0.0


def test_matching_with_no_answer_at_all():
    result = quiz_grading.grade(MATCHING, {})
    assert result["correct"] is False
    assert result["points"] == 0.0


def test_partial_matching_is_never_correct():
    # The load-bearing half of the contract: a partly right answer must not
    # clear a checkpoint gate (chemie-data-contract.md § 4a) or a warm-up streak.
    answer = {left: right for left, right in MATCHING["pairs"]}
    answer["Anode"] = "Reduktion"
    assert quiz_grading.grade(MATCHING, answer)["correct"] is False


# --- presentation: what reaches the client ----------------------------------

def test_ordering_presentation_carries_no_answer_key():
    payload = quiz_grading.presentation(ORDERING, random.Random(0))
    assert set(payload) == {"items"}
    assert sorted(payload["items"]) == sorted(ORDERING["items"])


def test_ordering_presentation_does_not_hand_over_the_authored_order():
    # With four items an unlucky shuffle lands on the solution one time in 24;
    # _shuffled retries rather than showing a question that is already solved.
    for seed in range(30):
        payload = quiz_grading.presentation(ORDERING, random.Random(seed))
        assert payload["items"] != ORDERING["items"]


def test_matching_presentation_mixes_distractors_into_the_right_column():
    payload = quiz_grading.presentation(MATCHING, random.Random(1))
    assert set(payload) == {"left", "right"}
    assert sorted(payload["left"]) == sorted(left for left, _ in MATCHING["pairs"])
    assert sorted(payload["right"]) == sorted(
        [right for _, right in MATCHING["pairs"]] + MATCHING["distractors"])


def test_matching_presentation_does_not_pair_the_columns_by_position():
    # Left and right are shuffled independently; if position survived, reading
    # the two lists in order would spell out the answer key.
    aligned = 0
    for seed in range(20):
        payload = quiz_grading.presentation(MATCHING, random.Random(seed))
        pairs = dict(MATCHING["pairs"])
        if all(pairs[left] == payload["right"][i] for i, left in enumerate(payload["left"])):
            aligned += 1
    assert aligned == 0


# --- readable renderings ----------------------------------------------------

def test_correct_answer_text_reads_as_a_solution():
    assert quiz_grading.correct_answer_text(ORDERING).startswith("Aufgabe lesen → Material")
    assert "Anode → Oxidation" in quiz_grading.correct_answer_text(MATCHING)


def test_answer_text_names_the_rows_the_student_left_empty():
    text = quiz_grading.answer_text(MATCHING, {"Anode": "Oxidation"})
    assert "Anode → Oxidation" in text
    assert "Kathode → ?" in text
