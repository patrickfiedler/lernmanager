"""Deterministic grading and display prep for the `ordering` and `matching`
question types.

Both are graded here rather than in llm_grading.py because both are decidable
from the quiz JSON alone -- no model call, no rate limit, no quota. That is the
main reason they are cheap enough to put in a warm-up.

Answers travel as *item text*, never as an index into the authored list. An
index-based protocol would have to send the client the mapping it needs to
grade, which is the answer key (see tests/test_warmup_answer_key_leak.py);
text-based grading has nothing to leak. The price is that an author must keep
the entries of one question distinct -- import validation enforces it.

Scoring (one fixed rule, documented in docs/shared/lernmanager/task_json_format.md
and docs/shared/chemie-data-contract.md):

    fraction = correct units / total units
        matching: correct pairs / number of pairs
        ordering: correct adjacent pairs / (number of items - 1)
    points   = fraction floored to the nearest half point
    correct  = fraction == 1.0

Flooring rather than rounding is deliberate: 3 of 4 pairs scores 0.5, not 0.75,
and 1 of 3 scores nothing. A near-miss never rounds up into a point it did not
earn. `correct` stays all-or-nothing everywhere, so a partly-right answer never
passes a checkpoint gate or a warm-up streak -- it only earns partial points and
a feedback line saying how far off it was.
"""
import math
import random

ORDERING = 'ordering'
MATCHING = 'matching'

#: Types this module grades. Deterministic, fast, safe in a warm-up.
INTERACTIVE_TYPES = (ORDERING, MATCHING)


def is_interactive(qtype):
    return qtype in INTERACTIVE_TYPES


def points_for(fraction):
    """Floor a 0..1 fraction to the nearest half point.

    The round() guards float noise: 3/5 * 2 is 1.2000000000000002, and one
    unlucky representation below an exact 1.0 would silently drop a full point.
    """
    return math.floor(round(fraction * 2, 9)) / 2


def _texts(values):
    """Normalise a client-supplied answer to a list of stripped strings."""
    if not isinstance(values, (list, tuple)):
        return []
    return [str(v).strip() for v in values]


def _pair_list(question):
    """The authored pairs as [(left, right), ...], skipping malformed entries."""
    return [(str(p[0]), str(p[1]))
            for p in question.get('pairs', [])
            if isinstance(p, (list, tuple)) and len(p) >= 2]


def grade_ordering(question, answer):
    """Grade one ordering answer.

    `answer` is the item texts in the order the student put them. Partial
    credit counts correct *adjacencies* -- "B directly after A" -- rather than
    absolute positions, because a sequence shifted by one wrong entry at the
    front still shows the student knows the sequence. MBI proposed the measure;
    it is the one documented rule for this type.
    """
    items = [str(i) for i in question.get('items', [])]
    submitted = _texts(answer)
    total = max(len(items) - 1, 0)

    # A submission that is not a permutation of the items cannot be scored --
    # a tampered or stale client payload, not a wrong answer with a near-miss.
    if sorted(submitted) != sorted(items):
        return _result(0, total, False,
                       'Die Reihenfolge konnte nicht gelesen werden. Versuch es noch einmal.')

    correct_adjacencies = {(items[i], items[i + 1]) for i in range(total)}
    right = sum(1 for i in range(len(submitted) - 1)
                if (submitted[i], submitted[i + 1]) in correct_adjacencies)
    is_right = submitted == items

    if is_right:
        return _result(total, total, True, 'Richtig!')
    if total == 0:
        return _result(0, 0, False, 'Leider falsch.')
    return _result(right, total, False,
                   f'{right} von {total} Übergängen stimmen — die Reihenfolge ist noch nicht ganz richtig.')


def grade_matching(question, answer):
    """Grade one matching answer.

    `answer` maps left text -> chosen right text. A left entry with no choice
    counts as wrong; a choice that is one of the `distractors` is simply not
    the expected right text, so it counts as wrong too, with no special case.
    """
    pairs = _pair_list(question)
    total = len(pairs)
    chosen = answer if isinstance(answer, dict) else {}

    right = sum(1 for left, expected in pairs
                if str(chosen.get(left, '')).strip() == expected)
    is_right = right == total and total > 0

    if is_right:
        return _result(right, total, True, 'Richtig!')
    return _result(right, total, False,
                   f'{right} von {total} Paaren richtig zugeordnet.')


def grade(question, answer):
    """Dispatch to the grader for this question's type."""
    qtype = question.get('type')
    if qtype == ORDERING:
        return grade_ordering(question, answer)
    if qtype == MATCHING:
        return grade_matching(question, answer)
    raise ValueError(f'not an interactive question type: {qtype!r}')


def _result(right, total, correct, feedback):
    fraction = 1.0 if correct else (right / total if total else 0.0)
    return {
        'right': right,
        'total': total,
        'correct': correct,
        'fraction': fraction,
        'points': points_for(fraction),
        'feedback': feedback,
    }


def presentation(question, rng=None):
    """Client-safe payload: the pieces to display, in shuffled order.

    Carries no answer key. For `ordering` the authored order is the answer, so
    the items must arrive shuffled; for `matching` the right column is shuffled
    together with the distractors, so a distractor is indistinguishable from a
    real partner.
    """
    rng = rng or random
    qtype = question.get('type')

    if qtype == ORDERING:
        items = [str(i) for i in question.get('items', [])]
        shuffled = _shuffled(items, rng, avoid=items)
        return {'items': shuffled}

    if qtype == MATCHING:
        pairs = _pair_list(question)
        left = [p[0] for p in pairs]
        right = [p[1] for p in pairs] + [str(d) for d in question.get('distractors', [])]
        rng.shuffle(left)
        return {'left': left, 'right': _shuffled(right, rng)}

    raise ValueError(f'not an interactive question type: {qtype!r}')


def _shuffled(values, rng, avoid=None):
    """Shuffle a copy. With `avoid`, retry a few times rather than handing the
    student a list that is already in the correct order -- with three items that
    happens one time in six, and it reads as a bug ("it was already solved")."""
    out = list(values)
    for _ in range(10):
        rng.shuffle(out)
        if avoid is None or out != avoid or len(out) < 2:
            return out
    return out


def correct_answer_text(question):
    """Human-readable solution, for the give-up path and result pages."""
    qtype = question.get('type')
    if qtype == ORDERING:
        items = [str(i) for i in question.get('items', [])]
        return ' → '.join(items)
    if qtype == MATCHING:
        return '; '.join(f'{left} → {right}' for left, right in _pair_list(question))
    return ''


def answer_text(question, answer):
    """Human-readable rendering of what the student submitted."""
    qtype = question.get('type')
    if qtype == ORDERING:
        return ' → '.join(_texts(answer))
    if qtype == MATCHING:
        if not isinstance(answer, dict):
            return ''
        return '; '.join(f'{left} → {answer.get(left) or "?"}'
                         for left, _ in _pair_list(question))
    return ''
