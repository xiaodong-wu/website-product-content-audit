#!/usr/bin/env python3
"""Validate an evidence manifest and prepare selected-priority report data."""
import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def text(obj, key, where):
    value = obj.get(key)
    require(isinstance(value, str) and value.strip(), f'{where}.{key}: nonempty string required')
    return value.strip()


def url(value):
    require(isinstance(value, str), 'URL must be a string')
    try:
        p = urlsplit(value.strip())
        require(p.scheme in ('http', 'https') and p.hostname and not p.username and not p.password,
                'HTTP(S) URL without credentials required')
        p.port
    except ValueError as error:
        raise AuditError(f'Invalid URL: {error}') from error
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', p.query, ''))


def stamp(value):
    require(isinstance(value, str), 'Timestamp must be an ISO 8601 string')
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise AuditError('Invalid ISO 8601 timestamp') from error
    require(d.utcoffset() is not None, 'Timestamp must include a timezone')
    return d


def status(value):
    require(value is None or (type(value) is int and 100 <= value <= 599), 'Invalid HTTP status')


def prepare(data, priorities=('P1',)):
    require(data.get('schema_version') == 1, 'schema_version must be 1')
    require(priorities and set(priorities) <= {'P1', 'P2', 'P3'}, 'Invalid priority selection')
    site, coverage, products = data.get('site', {}), data.get('coverage', {}), data.get('products')
    text(site, 'name', 'site'); url(site.get('url')); stamp(site.get('checked_at'))
    require(isinstance(products, list), 'products must be a list')
    require(coverage.get('scope') in ('site', 'selected'), 'coverage.scope must be site or selected')
    require(type(coverage.get('discovery_complete')) is bool, 'discovery_complete must be boolean')
    sources, limitations = coverage.get('sources'), coverage.get('limitations')
    require(isinstance(sources, list) and sources, 'At least one discovery source required')
    require(isinstance(limitations, list) and all(isinstance(x, str) and x.strip() for x in limitations),
            'limitations must be a list of nonempty strings')
    for s in sources:
        url(s.get('url')); stamp(s.get('checked_at')); text(s, 'kind', 'source')
    ids, current_urls, all_issues = set(), set(), set()
    for p in products:
        pid = text(p, 'id', 'product'); text(p, 'name', pid)
        require(pid not in ids, f'Duplicate product id: {pid}'); ids.add(pid)
        current = url(p.get('current_url'))
        require(current not in current_urls, f'Duplicate current URL: {current}'); current_urls.add(current)
    retired = set()
    for r in data.get('retired_urls', []):
        old, replacement = url(r.get('url')), url(r.get('replacement_url'))
        require(old not in current_urls and old != replacement, 'Retired URL is still a current product')
        require(old not in retired, 'Duplicate retired URL'); retired.add(old)
        require(replacement in current_urls, 'Replacement must be a current product')
        require(r.get('identity_confirmed') is True and r.get('new_status') == 200 and
                r.get('new_body_matches_product') is True, 'Retirement needs verified product identity and new page')
        require(url(r.get('catalog_href')) == replacement, 'Catalog must point to the replacement')
        url(r.get('catalog_url')); stamp(r.get('checked_at'))
    output_products, output_issues, reviews, excluded = [], [], Counter(), Counter()
    for p in products:
        pid, current = p['id'], url(p['current_url'])
        review = p.get('review_status')
        require(review in ('reviewed', 'unavailable', 'pending'), f'{pid}: invalid review_status')
        reviews[review] += 1
        stamp(p.get('checked_at')); status(p.get('http_status'))
        checks = p.get('access_checks')
        require(isinstance(checks, list), f'{pid}: access_checks must be a list')
        relevant = []
        for c in checks:
            checked = stamp(c.get('checked_at')); status(c.get('status'))
            source, final = url(c.get('url')), url(c.get('final_url'))
            require(type(c.get('live')) is bool, f'{pid}: live must be boolean')
            require(c.get('body_matches_product') is None or type(c.get('body_matches_product')) is bool, f'{pid}: invalid body_matches_product')
            if source == current and c['live']:
                relevant.append((checked, c, final))
        latest = max(relevant, key=lambda x: x[0]) if relevant else None
        require(not latest or p.get('http_status') == latest[1]['status'], f'{pid}: HTTP status differs from latest check')
        if review == 'reviewed':
            require(latest and latest[1]['status'] == 200 and latest[1].get('body_matches_product') is True,
                    f'{pid}: reviewed content needs a live matching 200 response')
        if review == 'unavailable':
            require(latest is not None, f'{pid}: access-only review needs a live check')
        selected = []
        require(isinstance(p.get('issues'), list), f'{pid}: issues must be a list')
        for item in p['issues']:
            iid = text(item, 'id', pid)
            require(iid not in all_issues, f'Duplicate issue id: {iid}'); all_issues.add(iid)
            require(item.get('priority') in ('P1', 'P2', 'P3'), f'{iid}: invalid priority')
            require(item.get('state') in ('open', 'resolved', 'needs_review'), f'{iid}: invalid state')
            require(type(item.get('confirmed')) is bool, f'{iid}: confirmed must be boolean')
            if item['state'] != 'open':
                excluded[item['state']] += 1
                continue
            if item['priority'] == 'P1':
                require(item['confirmed'], f'{iid}: unconfirmed open P1; review or mark needs_review')
            if item['priority'] not in priorities or not item['confirmed']:
                excluded['other_priority_or_unconfirmed'] += 1
                continue
            for field in ('title', 'location', 'impact', 'recommendation'):
                text(item, field, iid)
            require(item.get('kind') in ('content', 'access'), f'{iid}: invalid kind')
            evidence = item.get('evidence')
            require(isinstance(evidence, list) and evidence, f'{iid}: evidence required')
            evidence_urls = []
            for e in evidence:
                eu = url(e.get('url')); evidence_urls.append(eu)
                require(eu not in retired, f'{iid}: active issue cites retired URL')
                text(e, 'text', iid); text(e, 'location', iid)
            require(current in evidence_urls, f'{iid}: at least one current-page evidence required')
            if item['kind'] == 'content':
                require(review == 'reviewed', f'{iid}: content issues need reviewed content')
            else:
                bad = [(t, c) for t, c, final in relevant if c['status'] in (404, 410)]
                require(len({t for t, c in bad}) >= 2 and latest and latest[1]['status'] in (404, 410),
                        f'{iid}: access issue needs repeated live 404/410 and no later success')
                ce = item.get('catalog_evidence', {})
                url(ce.get('url')); stamp(ce.get('checked_at'))
                require(url(ce.get('href')) == current, f'{iid}: current catalog href must match failed URL')
            row = {k: item[k] for k in ('id', 'priority', 'kind', 'title', 'location', 'impact', 'recommendation')}
            row.update(product_id=pid, product_name=p['name'], current_url=current,
                       evidence='\n'.join(f"{e['location']}：{e['text']}\n来源：{e['url']}" for e in evidence))
            selected.append(row); output_issues.append(row)
        if selected:
            output_products.append({'id': pid, 'name': p['name'], 'model': p.get('model', ''),
                'category': p.get('category', ''), 'current_url': current, 'http_status': p.get('http_status'),
                'checked_at': p['checked_at'], 'issue_count': len(selected),
                'highest_priority': min(x['priority'] for x in selected),
                'summary': '\n'.join(f"[{x['priority']}] {x['title']}" for x in selected)})
    summary = {'products_discovered': len(products), 'content_reviewed': reviews['reviewed'],
               'access_only': reviews['unavailable'], 'pending': reviews['pending'],
               'affected_products': len(output_products), 'issues': len(output_issues),
               'by_priority': dict(Counter(x['priority'] for x in output_issues)),
               'excluded': dict(excluded), 'retired_urls': len(retired)}
    return {'schema_version': 1, 'site': site, 'coverage': coverage, 'priorities': list(priorities),
            'summary': summary, 'products': output_products, 'issues': output_issues}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--priorities', nargs='+', choices=('P1', 'P2', 'P3'), default=['P1'])
    args = ap.parse_args()
    try:
        report = prepare(json.loads(args.input.read_text(encoding='utf-8')), tuple(dict.fromkeys(args.priorities)))
    except (AuditError, ValueError, KeyError, TypeError, AttributeError) as error:
        ap.exit(2, f'Invalid audit: {error}\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
