"""Markdown lists in authored content.

Every Aufgabe is authored as "📋 Aufgabe:" directly above "1. ...", and
Markdown does not let a list interrupt a paragraph -- so all 33 descriptions
in the DB rendered as one paragraph of literal "1." text with <br> between
the lines. It was invisible because the CSS and the filter both looked
correct; only the rendered HTML showed it.
"""
import markdown as md
import pytest

from utils import normalize_markdown_lists

EXT = ['nl2br', 'fenced_code', 'tables', 'sane_lists']


def render(text):
    return md.markdown(normalize_markdown_lists(text), extensions=EXT, tab_length=3)


def test_numbered_steps_under_a_marker_become_a_list():
    html = render("📋 Aufgabe:\n1. Erster Schritt.\n2. Zweiter Schritt.")
    assert '<ol>' in html
    assert html.count('<li>') == 2


def test_bullets_under_a_text_line_become_a_list():
    html = render("Ein Dokument mit zwei Seiten:\n- Seite 1\n- Seite 2")
    assert '<ul>' in html
    assert html.count('<li>') == 2


def test_sub_items_nest_inside_their_step():
    html = render("📋 Aufgabe:\n1. Erster Schritt.\n   - Unterpunkt\n2. Zweiter Schritt.")
    assert html.count('<ol>') == 1
    assert '<ul>' in html


def test_a_wrapped_item_does_not_split_the_list():
    """The bug this guards: inserting a blank line before every marker would
    turn one list into several as soon as an item wraps onto its own line."""
    html = render("📋 Aufgabe:\n1. Erster Schritt,\n   der weitergeht.\n2. Zweiter Schritt.")
    assert html.count('<ol>') == 1


def test_a_list_already_separated_is_left_alone():
    text = "📋 Aufgabe:\n\n1. Erster Schritt.\n2. Zweiter Schritt."
    assert normalize_markdown_lists(text) == text


def test_fenced_code_is_never_touched():
    text = "Beispiel:\n```\n1. kein Listenpunkt\n- auch nicht\n```"
    assert normalize_markdown_lists(text) == text
    assert '<ol>' not in render(text)


def test_a_table_is_not_mistaken_for_a_list():
    html = render("Tabelle:\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert '<table>' in html
    assert '<li>' not in html


@pytest.mark.parametrize('text', [
    "📋 Aufgabe:\n1. Eins\n2. Zwei",
    "Text\n- a\n- b",
    "\n\n1. Eins\n\nSchlusstext",
    "### Titel\n1. Eins",
    "Nur Fließtext ohne jede Liste.",
    "1. Eins\n2. Zwei",
    "|a|b|\n|---|---|\n|1|2|",
    "```\n1. nein\n```",
    "> 1. Zitat mit Liste",
    "",
])
def test_normalizing_never_removes_list_items(text):
    """The invariant that makes this safe to apply to every existing field:
    the normalizer may add list items, never drop one."""
    before = md.markdown(text, extensions=EXT, tab_length=3).count('<li>')
    assert render(text).count('<li>') >= before
