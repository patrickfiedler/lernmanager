"""Step ticks across content edits.

A ticked work step is stored as a key: a hash of the step's text, computed in
the browser (templates/student/klasse.html, "Arbeitsschritte abhaken"). Keys
make ticks survive reordering, but a reworded step gets a new key and its tick
is lost. This module computes the same keys from the Markdown on the server, so
a content edit can carry ticks from the old wording to the new one.

The text rule must stay identical to the browser's: top-level `ol > li`, nested
lists removed, whitespace collapsed, djb2 over UTF-16 code units, base 36.
"""
import difflib
import re
from html.parser import HTMLParser

# A reworded step must be at least this similar to its old wording to keep the
# tick. Only steps of the same Aufgabe compete, and a wrong match costs one
# scratch tick, so this can be looser than a check that decides a gate.
MIN_SIMILARITY = 0.6


class _StepCollector(HTMLParser):
    """Text of every `li` in an `ol` that is not itself inside an `li`,
    without the text of nested lists (`ul`/`ol` inside it)."""

    VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'wbr', 'source', 'col', 'area'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []       # open tags
        self.steps = []
        self.current = None   # text parts of the step being read
        self.step_depth = None
        self.skip_depth = None

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        self.stack.append(tag)
        depth = len(self.stack)
        if self.current is None:
            if tag == 'li' and len(self.stack) >= 2 and self.stack[-2] == 'ol' \
                    and 'li' not in self.stack[:-1]:
                self.current, self.step_depth = [], depth
        elif self.skip_depth is None and tag in ('ul', 'ol'):
            self.skip_depth = depth

    def handle_endtag(self, tag):
        if tag in self.VOID or tag not in self.stack:
            return
        while self.stack:
            depth = len(self.stack)
            open_tag = self.stack.pop()
            if self.skip_depth == depth:
                self.skip_depth = None
            if self.step_depth == depth:
                self.steps.append(re.sub(r'\s+', ' ', ''.join(self.current)).strip())
                self.current = self.step_depth = None
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self.current is not None and self.skip_depth is None:
            self.current.append(data)


def step_texts(html):
    """Texts of the work steps in rendered task HTML, in page order."""
    parser = _StepCollector()
    parser.feed(str(html))
    parser.close()
    return parser.steps


def step_key(text):
    """The browser's key for a step text (djb2, signed 32 bit, base 36)."""
    h = 5381
    units = text.encode('utf-16-le')
    for i in range(0, len(units), 2):
        c = units[i] | (units[i + 1] << 8)
        h = ((h << 5) + h + c) & 0xFFFFFFFF
    return _base36(h)


def _base36(n):
    digits = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = ''
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            return out


def successors(old_texts, new_texts):
    """Map each removed step's key to the key of the step it became.

    One assignment over all steps, not per tick: candidate pairs are claimed
    in order of similarity (ties: smaller shift in position), each old and new
    step at most once. A changed step that shares a file name with a different
    new step then loses that step to its real successor -- measured on MBI's
    unit history (2026-11-28): "Kopiere ... .pptx auf den USB-Stick" 0.74 vs.
    the real successor "Öffne deine Datei ... .pptx im Ordner ..." 0.78.
    Position is only a tie-break: reworded steps move often (inserted or
    merged steps), a window on position would lose most of them.
    """
    old_keys = [step_key(t) for t in old_texts]
    new_keys = [step_key(t) for t in new_texts]
    gone = [(i, t, k) for i, (t, k) in enumerate(zip(old_texts, old_keys)) if k not in new_keys]
    fresh = [(j, t, k) for j, (t, k) in enumerate(zip(new_texts, new_keys)) if k not in old_keys]
    pairs = []
    for i, old_text, old_key in gone:
        for j, new_text, new_key in fresh:
            ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
            if ratio >= MIN_SIMILARITY:
                pairs.append((-ratio, abs(i - j), old_key, new_key))
    mapping, taken = {}, set()
    for _, _, old_key, new_key in sorted(pairs):
        if old_key not in mapping and new_key not in taken:
            mapping[old_key] = new_key
            taken.add(new_key)
    return mapping


def remap_ticks(ticked_keys, old_texts, new_texts):
    """Keys to store after the steps changed from old_texts to new_texts.

    A key whose step is still there stays (also when the step moved). A key
    whose step was reworded moves to its successor. Anything else is dropped,
    as the browser would drop it on the next save.
    """
    new_keys = {step_key(t) for t in new_texts}
    mapping = successors(old_texts, new_texts)
    kept = {k for k in ticked_keys if k in new_keys}
    kept |= {mapping[k] for k in ticked_keys if k in mapping}
    return sorted(kept)
