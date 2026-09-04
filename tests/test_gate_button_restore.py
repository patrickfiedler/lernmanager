"""A passing gate hides its submit button; picking a new file must bring it back.

Reported from production: a student uploads, the check passes structurally, and the AI
feedback beside it says the work still needs another round. The student picks a corrected
file right there instead of clicking "Weiter →" -- and the submit button is gone, because
the success branch set display:none and nothing ever undid it. "Datei auswählen" stays
visible, "Datei prüfen" does not, and only a page reload gets it back.

A second bug rode on the same code (2026-08-30): the button came back still wearing the
spinner and "Datei wird geprüft …", because the click handler swapped that label in by
hand and only the failure branches swapped it back.

**Rewritten 2026-09-04.** Both gates now share one implementation (`wireGateCard`), and
the busy label goes through `LLMButton.withBusy`, whose restore runs on every exit path.
So the label bug is no longer prevented by counting matched restores -- it is structurally
impossible, and the counting assertions that used to pin it were pinning the duplication
instead. What is still worth pinning: one implementation rather than two, the display
restore living in the change handler, and nobody re-introducing a hand-rolled busy label.

This is a source-level guard, not a behavioural test: the bug lives in a DOM property no
Flask response reveals, and pytest cannot click a file input. Real verification is one
manual click-through, or a suite in scripts/browser_tests/.
"""
import os
import re

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates', 'student', 'klasse.html')


def _source():
    with open(TEMPLATE, encoding='utf-8') as f:
        return f.read()


def test_one_implementation_wired_for_both_gates():
    """The duplication itself was the defect: the two copies had already drifted once
    (the inline gate silently dropped llm_feedback, f6a4402). One body, two calls."""
    source = _source()
    assert source.count('function wireGateCard(') == 1
    calls = re.findall(r"wireGateCard\('([\w-]+)'", source)
    assert sorted(calls) == ['gate', 'inline-gate'], \
        f"expected the capstone and inline gates to share the body, found {calls}"


def test_every_hide_is_matched_by_a_restore():
    """One success branch hides the button; one change handler brings it back."""
    source = _source()
    hides = len(re.findall(r"submitBtn\.style\.display\s*=\s*'none'", source))
    restores = len(re.findall(r"submitBtn\.style\.display\s*=\s*''", source))
    assert hides == 1, f"expected 1 hide in the shared body, found {hides}"
    assert restores == 1, f"expected 1 restore in the change handler, found {restores}"


def test_restore_sits_in_the_file_change_handler():
    """The restore has to fire when a new file is picked -- that is the moment the
    student needs the button back. Anywhere else and the reload stays mandatory."""
    source = _source()
    handlers = re.findall(
        r"fileInput\.addEventListener\('change'.*?\}\);", source, re.S)
    assert len(handlers) == 1, f"expected 1 shared change handler, found {len(handlers)}"
    assert "submitBtn.style.display = ''" in handlers[0]
    assert 'submitBtn.disabled = !name' in handlers[0]


def test_busy_label_is_delegated_not_hand_rolled():
    """The 2026-08-30 label bug is now prevented by construction: withBusy captures the
    button's markup before it spins and restores it on success, failure, timeout and
    network error alike. A hand-written label swap here would reopen the hole, because
    nothing would put it back on the success branch."""
    source = _source()
    gate = re.search(r"function wireGateCard\(.*?\n\}", source, re.S)
    assert gate, "wireGateCard not found"
    body = gate.group(0)

    assert 'LLMButton.withBusy(submitBtn' in body, \
        "the gate must go through withBusy, which restores on every exit path"
    assert 'llm-busy-label' not in body, \
        "hand-rolling the busy label is what froze the spinner on the success branch"
    assert "submitBtn.textContent = 'Datei prüfen'" not in body, \
        "withBusy restores the original markup; a manual reset would mask a real bug"


def test_re_entry_is_blocked_while_a_check_runs():
    """One click, one upload. The old hand-rolled version relied solely on the disabled
    attribute; isBusy blocks every path, including a programmatic call."""
    source = _source()
    gate = re.search(r"function wireGateCard\(.*?\n\}", source, re.S)
    assert 'LLMButton.isBusy(submitBtn)' in gate.group(0)
