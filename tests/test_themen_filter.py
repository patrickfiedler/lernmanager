"""The /admin/themen table ships filter options and sort keys for the client-side
filter/sort controls."""
import models


def _seed():
    models.create_task("Zehner", "", "", "MBI", "10", "pflicht")
    models.create_task("Fuenfer", "", "", "MBI", "5", "bonus")
    models.create_task("Chemie-Modul", "", "", "Chemie", "11/12", "pflicht")


def test_filter_options_come_from_existing_topics(as_admin, db):
    _seed()
    html = as_admin.get("/admin/themen").get_data(as_text=True)

    assert '<option value="MBI">MBI</option>' in html
    assert '<option value="Chemie">Chemie</option>' in html
    # Grade options are ordered numerically, not as text ('10' after '5').
    assert html.index('<option value="5">') < html.index('<option value="10">')
    assert html.index('<option value="10">') < html.index('<option value="11/12">')


def test_rows_carry_sort_and_filter_data(as_admin, db):
    _seed()
    html = as_admin.get("/admin/themen").get_data(as_text=True)

    assert 'data-stufe="10"' in html and 'data-stufe-key="10"' in html
    assert 'data-stufe="11/12"' in html and 'data-stufe-key="11"' in html
    assert 'data-kategorie="bonus"' in html


def test_default_row_order_is_numeric_by_grade(as_admin, db):
    _seed()
    html = as_admin.get("/admin/themen").get_data(as_text=True)

    assert html.index('data-name="Fuenfer"') < html.index('data-name="Zehner"')


def test_empty_library_skips_the_filter_bar(as_admin, db):
    html = as_admin.get("/admin/themen").get_data(as_text=True)

    assert "Noch keine Themen vorhanden." in html
    assert 'id="f-suche"' not in html
