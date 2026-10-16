#!/usr/bin/env python3
"""Verify exported data, links, cached counts and workbook structure against report.json."""
import argparse
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def verify(report, filename):
    def check(condition, message):
        if not condition:
            raise ValueError(message)
    with zipfile.ZipFile(filename) as z:
        check(z.testzip() is None, 'Corrupt ZIP')
        book = ET.fromstring(z.read('xl/workbook.xml'))
        check(len(book.find('m:sheets', NS)) == 2, 'Expected two sheets')
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(t.text or '' for t in s.findall('.//m:t', NS))
                       for s in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]

        def value(c):
            if c is None:
                return None
            t, v = c.get('t'), c.findtext('m:v', None, NS)
            if t == 's':
                return strings[int(v)]
            if t == 'inlineStr':
                return ''.join(x.text or '' for x in c.findall('.//m:t', NS))
            return v

        def expected(v):
            return str(v)

        sheets = []
        for i in (1, 2):
            tree = ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml'))
            cells = {c.get('r'): c for c in tree.findall('.//m:sheetData/m:row/m:c', NS)}
            check(not any(c.get('t') == 'e' for c in cells.values()), f'Sheet {i}: formula error')
            check(tree.find('.//m:pane', NS) is not None, f'Sheet {i}: frozen panes missing')
            table = ET.fromstring(z.read(f'xl/tables/table{i}.xml'))
            end = max(10, 10 + len(report['products'])) if i == 1 else max(7, 7 + len(report['issues']))
            ref = f'A10:J{end}' if i == 1 else f'A7:K{end}'
            check(table.get('ref') == ref, f'Sheet {i}: unexpected table range')
            check(table.find('m:autoFilter', NS) is not None, f'Sheet {i}: filter missing')
            sheets.append(cells)
        total = 0
        for row, p in enumerate(report['products'], 11):
            c = sheets[0]
            fields = {'A': p['id'], 'B': p['name'], 'C': p['model'], 'D': p['category'],
                      'E': p['highest_priority'], 'F': p['summary'], 'H': p['current_url'],
                      'I': p['http_status'] if p['http_status'] is not None else '待确认', 'J': f'核查于：{p["checked_at"]}'}
            for col, want in fields.items():
                actual = value(c.get(f'{col}{row}'))
                check(actual == expected(want) or (want == '' and actual is None), f'Product {p["id"]}: {col} mismatch')
                check(c.get(f'{col}{row}') is None or c[f'{col}{row}'].find('m:f', NS) is None, 'Source text became a formula')
            count = int(value(c.get(f'G{row}')))
            check(count == p['issue_count'], 'Per-product issue count mismatch')
            total += count
        check(total == len(report['issues']), 'Total issue count mismatch')
        for row, item in enumerate(report['issues'], 8):
            fields = {'A': 'id', 'B': 'product_id', 'C': 'product_name', 'D': 'priority',
                      'E': 'location', 'F': 'title', 'G': 'evidence', 'H': 'impact',
                      'I': 'recommendation', 'J': 'current_url'}
            for col, key in fields.items():
                check(value(sheets[1].get(f'{col}{row}')) == expected(item[key]), f'Issue {item["id"]}: {key} mismatch')
                check(sheets[1][f'{col}{row}'].find('m:f', NS) is None, 'Issue source text became a formula')
            check(item['priority'] in report['priorities'], 'Unexpected priority')
    return {'valid': True, 'products': len(report['products']), 'issues': len(report['issues']), 'formula_errors': 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report', type=Path)
    ap.add_argument('workbook', type=Path)
    args = ap.parse_args()
    try:
        result = verify(json.loads(args.report.read_text(encoding='utf-8')), args.workbook)
    except (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, TypeError) as error:
        ap.exit(2, f'Workbook verification failed: {error}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
