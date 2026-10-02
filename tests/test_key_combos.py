"""Tastenkombinationen in Aufgabe texts are shown as keys (<kbd>).

Requested by mbi
(docs/shared/requests/2026-10-02-mbi-tastenkombinationen-als-tasten-anzeigen-strg-s-windows.md).
"""
import pytest

import config
import key_combos
from app import markdown_filter


def render(text):
    return str(markdown_filter(text))


def keys(html):
    return [part.split('</kbd>')[0] for part in html.split('<kbd>')[1:]]


def test_three_keys_in_a_tipp():
    html = render("Einen Screenshot machst du mit Windows + Umschalt + S.")
    assert keys(html) == ['Windows', 'Umschalt', 'S']
    assert '<span class="key-combo"><kbd>Windows</kbd> + <kbd>Umschalt</kbd> + <kbd>S</kbd></span>.' in html


def test_without_blanks():
    assert keys(render("Füge mit Strg+V ein.")) == ['Strg', 'V']


@pytest.mark.parametrize('text', [
    "Rechne 2 + 3.",
    "Bild + Text gehören zusammen.",
    "Drücke Strg und dann S.",
    "Die Strg-Taste ist unten links.",
])
def test_plain_text_stays_plain(text):
    assert '<kbd>' not in render(text)


def test_only_the_chain_becomes_keys():
    html = render("Drücke Strg + S und speichere.")
    assert keys(html) == ['Strg', 'S']
    assert '</span> und speichere.' in html


def test_altgr_is_one_key():
    assert keys(render("AltGr + Q")) == ['AltGr', 'Q']


def test_non_key_link_is_shown_as_key_too():
    assert keys(render("Strg + Mausrad")) == ['Strg', 'Mausrad']


def test_code_span_is_left_alone():
    html = render("Tippe `Strg + S` ab.")
    assert '<kbd>' not in html
    assert '<code>Strg + S</code>' in html


def test_inside_list_and_bold():
    html = render("1. Drücke **Strg + C**.\n2. Drücke Alt + F4.")
    assert keys(html) == ['Strg', 'C', 'Alt', 'F4']
    assert html.count('<li>') == 2


def test_chain_does_not_run_over_a_line_break():
    html = render("Drücke Strg +\nS ist ein Buchstabe.")
    assert '<kbd>' not in html


def test_link_target_is_left_alone():
    html = render("[Suche](https://example.org/?q=Strg+S)")
    assert '<kbd>' not in html
    assert 'href="https://example.org/?q=Strg+S"' in html


def test_modifier_list_comes_from_config(monkeypatch):
    assert '<kbd>' not in render("Fn + F5")
    monkeypatch.setattr(config, 'KEY_COMBO_MODIFIERS', config.KEY_COMBO_MODIFIERS + ['Fn'])
    assert keys(render("Fn + F5")) == ['Fn', 'F5']


def test_empty_modifier_list_switches_it_off():
    import markdown
    html = markdown.markdown("Strg + S", extensions=[key_combos.KeyComboExtension([])])
    assert '<kbd>' not in html
