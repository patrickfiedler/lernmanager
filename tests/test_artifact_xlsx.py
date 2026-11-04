""".xlsx as an artifact: cell/chart extraction and the spreadsheet gate.

Kl.7 Unit 4 (Tabellenkalkulation) grades the workbook itself. The fixture is
built from raw XML in the shape Excel writes it: shared strings, a shared
formula, and a chart reached through sheet -> drawing -> chart relationships.
"""
import io
import zipfile

import artifact_checker
import artifact_processor
import import_task

_NS = ('xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _rels(*entries):
    body = ''.join(f'<Relationship Id="{i}" Type="{_REL}/{t}" Target="{target}"/>'
                   for i, t, target in entries)
    return ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{body}</Relationships>')


def _chart_xml(kind='barChart', bar_dir='col', title='Noten im Vergleich'):
    bar = f'<c:barDir val="{bar_dir}"/>' if kind == 'barChart' else ''
    return ('<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart>'
            f'<c:title><c:tx><c:rich><a:p><a:r><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title>'
            f'<c:plotArea><c:layout/><c:{kind}>{bar}</c:{kind}></c:plotArea>'
            '</c:chart></c:chartSpace>')


def make_xlsx(rows, chart=None, orphan_chart=False):
    """rows: list of (ref, value, formula-or-None). Strings go to sharedStrings."""
    strings, cells = [], []
    for ref, value, formula in rows:
        f = '' if formula is None else (
            '<f t="shared" si="0"/>' if formula == 'SHARED' else f'<f>{formula}</f>')
        if isinstance(value, str) and formula is None:
            strings.append(value)
            cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        else:
            cells.append(f'<c r="{ref}">{f}<v>{value}</v></c>')
    sheet_extra = '<drawing r:id="rId1"/>' if chart else ''
    files = {
        '[Content_Types].xml': '<Types/>',
        'xl/workbook.xml': f'<workbook {_NS}><sheets><sheet name="Noten" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': _rels(('rId1', 'worksheet', 'worksheets/sheet1.xml')),
        'xl/worksheets/sheet1.xml': (f'<worksheet {_NS}><sheetData><row r="1">{"".join(cells)}</row>'
                                     f'</sheetData>{sheet_extra}</worksheet>'),
        'xl/sharedStrings.xml': ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                 + ''.join(f'<si><t>{s}</t></si>' for s in strings) + '</sst>'),
    }
    if chart:
        files['xl/worksheets/_rels/sheet1.xml.rels'] = _rels(('rId1', 'drawing', '../drawings/drawing1.xml'))
        files['xl/drawings/drawing1.xml'] = '<xdr:wsDr xmlns:xdr="x"/>'
        files['xl/drawings/_rels/drawing1.xml.rels'] = _rels(('rId1', 'chart', '../charts/chart1.xml'))
        files['xl/charts/chart1.xml'] = _chart_xml(**chart)
    if orphan_chart:
        files['xl/charts/chart9.xml'] = _chart_xml()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


TEMPLATE = make_xlsx([('A1', 'Name', None), ('B1', 'Note', None)])
FILLED = make_xlsx([
    ('A1', 'Name', None), ('B1', 'Note', None),
    ('A2', 'Ali', None), ('B2', 2, None),
    ('A3', 'Bea', None), ('B3', 3, None),
    ('B4', 2.5, 'AVERAGE(B2:B3)'), ('C4', 5, 'SHARED'),
], chart={'kind': 'barChart', 'bar_dir': 'col'})


def test_cells_carry_ref_value_and_formula():
    cells = {b['ref']: b for b in artifact_processor.extract_xlsx_blocks(FILLED) if b['kind'] == 'cell'}
    assert cells['A2']['text'] == 'Ali' and cells['A2']['sheet'] == 'Noten'
    assert 'formula' not in cells['B2']                       # typed number
    assert cells['B4']['formula'] == 'AVERAGE(B2:B3)'
    assert cells['B4']['text'] == '2.5'
    assert cells['C4']['formula'] == ''                       # shared-formula follower


def test_chart_found_through_relationships_only():
    charts = [b for b in artifact_processor.extract_xlsx_blocks(FILLED) if b['kind'] == 'chart']
    assert [(c['chart_type'], c['text']) for c in charts] == [('säule', 'Noten im Vergleich')]
    # A chart part no sheet points to is not on the sheet.
    orphan = make_xlsx([('A1', 'x', None)], orphan_chart=True)
    assert not [b for b in artifact_processor.extract_xlsx_blocks(orphan) if b['kind'] == 'chart']


def test_bar_direction_and_pie_names():
    def kind(**chart):
        blocks = artifact_processor.extract_xlsx_blocks(make_xlsx([('A1', 'x', None)], chart=chart))
        return [b['chart_type'] for b in blocks if b['kind'] == 'chart']
    assert kind(kind='barChart', bar_dir='bar') == ['balken']
    assert kind(kind='pieChart') == ['kreis']


def test_rendered_text_shows_formulas_for_the_llm():
    text = artifact_processor.extract_artifact(FILLED, 'noten.xlsx')
    assert text.startswith('[Blatt Noten]')
    assert 'B4: =AVERAGE(B2:B3) → 2.5' in text
    assert 'B2: 2' in text
    assert 'Diagramm (säule): Noten im Vergleich' in text


def test_gate_counts_cells_formulas_charts():
    gate = {'format': ['.xlsx'], 'min_cells': 6, 'min_formulas': 2, 'min_charts': 1,
            'chart_types': ['säule', 'balken'],
            'required_text': [{'text': 'Note', 'kind': 'cell'}]}
    result = artifact_checker.check_gate(FILLED, 'noten.xlsx', gate)
    assert result['passed'], result['details']

    result = artifact_checker.check_gate(TEMPLATE, 'noten.xlsx', gate)
    assert not result['passed']
    joined = ' '.join(result['details'])
    assert 'Zu wenig Formeln (0, erwartet: 2)' in joined
    assert 'Zu wenig Diagramme' in joined
    assert 'Kein Diagramm der Art: säule oder balken' in joined


def test_gate_rejects_broken_file():
    result = artifact_checker.check_gate(b'PK\x03\x04 nope', 'noten.xlsx', {'format': ['.xlsx']})
    assert not result['passed']


def test_import_accepts_xlsx_gate_and_wants_template_for_added_cells():
    assert not import_task._uncheckable_gate_formats({'format': ['.xlsx']}, 'A1')
    _, warning = import_task._validate_artifact_gate(
        {'format': ['.xlsx'], 'min_added_cells': 4}, 'A1')
    assert 'template_material' in warning


def test_added_cells_by_position_and_changed_content():
    template = make_xlsx([('A1', 'Name', None), ('B1', 'Note', None), ('B2', 0, None)])
    student = make_xlsx([('A1', 'Name', None), ('B1', 'Note', None),
                         ('B2', 3, None),                 # placeholder changed -> counts
                         ('A2', 'Note', None)])           # same text, new place -> counts
    gate = {'format': ['.xlsx'], 'min_added_cells': 2, 'template_material': 'v.xlsx'}
    load = lambda name: template
    assert artifact_checker.check_gate(student, 'n.xlsx', gate, load)['passed']
    untouched = artifact_checker.check_gate(template, 'n.xlsx', gate, load)
    assert 'Zu wenig eigene Einträge (0, erwartet: 2)' in untouched['details']


def test_added_cells_without_template_only_warns():
    gate = {'format': ['.xlsx'], 'min_added_cells': 2, 'template_material': 'weg.xlsx'}
    result = artifact_checker.check_gate(FILLED, 'n.xlsx', gate, lambda name: None)
    assert result['passed'] and 'Vorlage zum Vergleich nicht gefunden' in result['warnings']
