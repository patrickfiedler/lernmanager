"""A passing gate hides its submit button; picking a new file must bring it back.

Reported from production: a student uploads, the check passes structurally, and the AI
feedback beside it says the work still needs another round. The student picks a corrected
file right there instead of clicking "Weiter →" -- and the submit button is gone, because
the success branch set display:none and nothing ever undid it. "Datei auswählen" stays
visible, "Datei prüfen" does not, and only a page reload gets it back.

This is a source-level guard, not a behavioural test: the bug lives in a DOM property no
Flask response reveals, and pytest cannot click a file input. It pins the pairing --
every branch that hides the button is matched by a restore in its gate's change handler
-- so the next person to add a hide sees this fail. Real verification is one manual
click-through, or a suite in scripts/browser_tests/.
"""
import os
import re

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates', 'student', 'klasse.html')


def _source():
    with open(TEMPLATE, encoding='utf-8') as f:
        return f.read()


def test_every_hide_is_matched_by_a_restore():
    """Two gates (inline + capstone), each hiding on its one success branch."""
    source = _source()
    hides = len(re.findall(r"submitBtn\.style\.display\s*=\s*'none'", source))
    restores = len(re.findall(r"submitBtn\.style\.display\s*=\s*''", source))
    assert hides == 2, f"expected 2 hides (1 success branch per gate), found {hides}"
    assert restores == 2, f"expected 1 restore per gate change handler, found {restores}"


def test_restore_sits_in_the_file_change_handler():
    """The restore has to fire when a new file is picked -- that is the moment the
    student needs the button back. Anywhere else and the reload stays mandatory."""
    source = _source()
    handlers = re.findall(
        r"fileInput\.addEventListener\('change'.*?\}\);", source, re.S)
    assert len(handlers) == 2, f"expected 2 change handlers, found {len(handlers)}"
    for handler in handlers:
        assert "submitBtn.style.display = ''" in handler
        assert 'submitBtn.disabled = !name' in handler


def test_the_restore_also_puts_the_label_back():
    """Reported 2026-08-30: pass a file, then pick a failing one -- the button came back
    still showing the spinner and "Datei wird geprüft …". The click handler swaps in that
    busy label, and only the three FAILURE branches swap it back; the success branch just
    hides the button, freezing the label inside it. So the change handler has to restore
    all three properties, not two."""
    source = _source()
    handlers = re.findall(
        r"fileInput\.addEventListener\('change'.*?\}\);", source, re.S)
    assert len(handlers) == 2
    for handler in handlers:
        assert "submitBtn.textContent = 'Datei prüfen'" in handler, \
            "un-hiding a button that still wears the busy label is not a restore"

    # Every busy-label swap on a GATE button is matched by a restore: 3 failure
    # branches + 1 change handler per gate. (The KI-Check button carries its own
    # llm-busy-label and is not affected -- it restores its label on every path.)
    busy = len(re.findall(r'llm-busy-label">Datei wird geprüft', source))
    restores = len(re.findall(r"submitBtn\.textContent = 'Datei prüfen'", source))
    assert busy == 2, f"expected 1 busy swap per gate, found {busy}"
    assert restores == 8, f"expected 4 label restores per gate, found {restores}"
