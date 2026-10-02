"""Key combinations in authored Markdown, shown as keys.

Content stays plain text:

    Einen Screenshot machst du mit Windows + Umschalt + S.

A chain of words joined by "+" that **starts with a known modifier key** becomes
one <kbd> per link. That start is what keeps "2 + 3" and "Bild + Text" as they
are. Requested by mbi
(docs/shared/requests/2026-10-02-mbi-tastenkombinationen-als-tasten-anzeigen-strg-s-windows.md).

Nothing here knows about Flask or config: the caller passes the modifier names.
"""
import re
import xml.etree.ElementTree as etree

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.util import AtomicString

# Blanks around the "+", but never a line break: with nl2br a newline is a <br>,
# and a combination does not continue on the next line.
_GAP = r'[ \t ]*'
# One key: letters and digits, umlauts included ("F4", "Mausrad", "Entf").
_KEY = r'[^\W_]+'


def combo_pattern(modifiers):
    """Regex for a chain like "Strg + S" or "Windows+Umschalt+S"."""
    # Longest first, so "AltGr" is not read as "Alt" followed by "Gr".
    names = '|'.join(re.escape(m) for m in sorted(modifiers, key=len, reverse=True))
    return rf'(?<!\w)(?:{names})(?:{_GAP}\+{_GAP}{_KEY})+'


class _KeyComboProcessor(InlineProcessor):
    def handleMatch(self, m, data):
        combo = etree.Element('span')
        combo.set('class', 'key-combo')
        last = None
        for name in re.split(r'\+', m.group(0)):
            if last is not None:
                last.tail = AtomicString(' + ')
            last = etree.SubElement(combo, 'kbd')
            # AtomicString: finished text, not to be searched for Markdown again.
            last.text = AtomicString(name.strip(' \t '))
        return combo, m.start(0), m.end(0)


class KeyComboExtension(Extension):
    def __init__(self, modifiers, **kwargs):
        self.modifiers = modifiers
        super().__init__(**kwargs)

    def extendMarkdown(self, md):
        if not self.modifiers:
            return
        # Low priority: code spans and links are already taken out by then, so
        # `Strg + S` in backticks and a "+" inside a URL stay untouched.
        md.inlinePatterns.register(
            _KeyComboProcessor(combo_pattern(self.modifiers), md), 'key_combos', 20)
