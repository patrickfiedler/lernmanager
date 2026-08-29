"""The 'Abgeschlossene Themen' dashboard section.

Covers the two rules that are easy to get wrong: a topic Stufe can be a range
covering two class years, and the level filter fails open rather than blanking
the section for the many classes that carry no klassenstufe.
"""
import pytest

from app import _build_completed_topic_list, _stufe_matches_klassenstufe


def topic(task_id, name, stufe='7', is_seilbahn=0):
    return {'task_id': task_id, 'name': name, 'stufe': stufe,
            'is_seilbahn': is_seilbahn}


class TestStufeMatching:
    def test_exact_year(self):
        assert _stufe_matches_klassenstufe('7', 7)
        assert not _stufe_matches_klassenstufe('7', 6)

    def test_range_covers_both_years(self):
        # A topic written for 11 and 12 belongs on both years' dashboards.
        assert _stufe_matches_klassenstufe('11/12', 11)
        assert _stufe_matches_klassenstufe('11/12', 12)
        assert not _stufe_matches_klassenstufe('11/12', 7)

    def test_legacy_range(self):
        assert _stufe_matches_klassenstufe('5/6', 5)
        assert _stufe_matches_klassenstufe('5/6', 6)

    def test_seilbahn_spelling_reduces_to_digits(self):
        assert _stufe_matches_klassenstufe('11s', 11)

    def test_fails_open_on_missing_data(self):
        # Most classes still carry klassenstufe = NULL; a strict test would
        # blank the section for them entirely.
        assert _stufe_matches_klassenstufe('7', None)
        assert _stufe_matches_klassenstufe(None, 7)
        assert _stufe_matches_klassenstufe('', 7)
        assert _stufe_matches_klassenstufe('Werkstatt', 7)


class TestBuildList:
    def test_off_by_default_shows_only_latest(self):
        completed = [topic(3, 'Drittes'), topic(2, 'Zweites'), topic(1, 'Erstes')]
        out = _build_completed_topic_list(completed, {}, False, 7)
        assert [e['name'] for e in out] == ['Drittes']

    def test_archive_shows_all(self):
        completed = [topic(3, 'Drittes'), topic(2, 'Zweites'), topic(1, 'Erstes')]
        out = _build_completed_topic_list(completed, {}, True, 7)
        assert [e['name'] for e in out] == ['Drittes', 'Zweites', 'Erstes']

    def test_level_filter_applies_before_the_latest_is_picked(self):
        # The newest topic is from last year: the student should see the newest
        # topic *of this year*, not nothing.
        completed = [topic(3, 'Letztes Jahr', stufe='6'), topic(2, 'Dieses Jahr', stufe='7')]
        out = _build_completed_topic_list(completed, {}, False, 7)
        assert [e['name'] for e in out] == ['Dieses Jahr']

    def test_level_filter_applies_to_archive_too(self):
        completed = [topic(3, 'Letztes Jahr', stufe='6'), topic(2, 'Dieses Jahr', stufe='7')]
        out = _build_completed_topic_list(completed, {}, True, 7)
        assert [e['name'] for e in out] == ['Dieses Jahr']

    def test_reopened_decorates_but_does_not_reorder(self):
        completed = [topic(3, 'Drittes'), topic(2, 'Zweites')]
        reopened = {2: {'student_feedback': 'Schau dir Aufgabe 3 nochmal an.'}}
        out = _build_completed_topic_list(completed, reopened, True, 7)
        assert [e['name'] for e in out] == ['Drittes', 'Zweites']
        assert out[0]['reopened'] is False
        assert out[1]['reopened'] is True
        assert out[1]['feedback'] == 'Schau dir Aufgabe 3 nochmal an.'

    def test_reopened_does_not_survive_the_default_cutoff(self):
        # Deliberate: the flag changes how an entry is drawn, not whether it is
        # in the list. An older reopened topic needs the archive turned on.
        completed = [topic(3, 'Drittes'), topic(2, 'Zweites')]
        out = _build_completed_topic_list(completed, {2: {'student_feedback': 'x'}}, False, 7)
        assert [e['name'] for e in out] == ['Drittes']

    def test_is_seilbahn_survives_for_slug_building(self):
        out = _build_completed_topic_list([topic(1, '5 - Thema', is_seilbahn=1)], {}, False, None)
        assert out[0]['is_seilbahn'] == 1

    def test_nothing_completed(self):
        assert _build_completed_topic_list([], {}, True, 7) == []
