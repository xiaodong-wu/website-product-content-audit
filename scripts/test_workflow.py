#!/usr/bin/env python3
"""Offline behavioral regression checks; fixtures are synthetic, no production requests."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prepare_report import AuditError, prepare
from probe_urls import probe

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / 'references/example-audit.json').read_text(encoding='utf-8'))


def failing_access():
    d = fixture()
    p = d['products'][0]
    p['review_status'], p['http_status'] = 'unavailable', 404
    p['access_checks'] = [dict(url=p['current_url'], final_url=p['current_url'], status=404,
        checked_at=f'2026-01-01T10:0{i}:00+08:00', live=True, body_matches_product=False) for i in (1, 2)]
    x = p['issues'][0]
    x.update(kind='access', title='当前目录链接失效', location='目录入口',
             evidence=[{'url': p['current_url'], 'location': '实时响应', 'text': '两次实时GET均返回404。'}],
             catalog_evidence={'url': 'https://example.com/products/', 'href': p['current_url'],
                               'checked_at': '2026-01-01T10:03:00+08:00'})
    d['retired_urls'] = []
    return d


class ManifestTests(unittest.TestCase):
    def test_p1_only_and_retirement(self):
        r = prepare(fixture())
        self.assertEqual((r['summary']['products_discovered'], len(r['products']), len(r['issues'])), (2, 1, 1))
        self.assertEqual(r['issues'][0]['id'], 'I001')
        self.assertNotIn('item-a-old', json.dumps(r['products']) + json.dumps(r['issues']))

    def test_explicit_priority_selection(self):
        self.assertEqual(len(prepare(fixture(), ('P1', 'P3'))['issues']), 2)

    def test_resolved_and_pending_not_exported(self):
        for state in ('resolved', 'needs_review'):
            d = fixture(); d['products'][0]['issues'][0]['state'] = state
            self.assertEqual(prepare(d)['summary']['issues'], 0)

    def test_unconfirmed_p1_rejected(self):
        d = fixture(); d['products'][0]['issues'][0]['confirmed'] = False
        with self.assertRaises(AuditError): prepare(d)

    def test_duplicate_product_ids(self):
        d = fixture(); d['products'][1]['id'] = 'P001'
        with self.assertRaises(AuditError): prepare(d)

    def test_duplicate_current_urls_ignore_fragment(self):
        d = fixture(); d['products'][1]['current_url'] = d['products'][0]['current_url'] + '#details'
        with self.assertRaises(AuditError): prepare(d)

    def test_query_variants_are_preserved(self):
        d = fixture(); d['retired_urls'] = []
        for i, p in enumerate(d['products']):
            p['current_url'] = f'https://example.com/item?variant={i}'
            p['access_checks'][0].update(url=p['current_url'], final_url=p['current_url'])
            for issue in p['issues']: issue['evidence'][0]['url'] = p['current_url']
        self.assertEqual(prepare(d)['summary']['products_discovered'], 2)

    def test_retirement_requires_current_catalog(self):
        d = fixture(); d['retired_urls'][0]['catalog_href'] = 'https://example.com/products/item-a-old'
        with self.assertRaises(AuditError): prepare(d)

    def test_old_evidence_cannot_be_relabelled(self):
        d = fixture(); d['products'][0]['issues'][0]['evidence'][0]['url'] = d['retired_urls'][0]['url']
        with self.assertRaises(AuditError): prepare(d)

    def test_duplicate_issue_ids(self):
        d = fixture(); d['products'][1]['issues'][0]['id'] = 'I001'
        with self.assertRaises(AuditError): prepare(d)

    def test_missing_evidence(self):
        d = fixture(); d['products'][0]['issues'][0]['evidence'] = []
        with self.assertRaises(AuditError): prepare(d)

    def test_unread_content_cannot_generate_content_issue(self):
        d = fixture(); d['products'][0]['review_status'] = 'pending'
        with self.assertRaises(AuditError): prepare(d)

    def test_access_only_requires_actual_probe(self):
        d = fixture(); d['products'][0].update(review_status='unavailable', access_checks=[], issues=[])
        with self.assertRaises(AuditError): prepare(d)

    def test_repeated_live_404_with_current_catalog(self):
        r = prepare(failing_access())
        self.assertEqual(r['summary']['access_only'], 1)
        self.assertEqual(r['issues'][0]['kind'], 'access')

    def test_single_404_is_insufficient(self):
        d = failing_access(); d['products'][0]['access_checks'].pop()
        with self.assertRaises(AuditError): prepare(d)

    def test_cached_404_is_insufficient(self):
        d = failing_access()
        for check in d['products'][0]['access_checks']: check['live'] = False
        with self.assertRaises(AuditError): prepare(d)

    def test_later_success_invalidates_404_issue(self):
        d = failing_access(); p = d['products'][0]
        p['http_status'] = 200
        p['access_checks'].append(dict(p['access_checks'][0], status=200, checked_at='2026-01-01T10:04:00+08:00', body_matches_product=True))
        with self.assertRaises(AuditError): prepare(d)

    def test_403_not_classified_as_missing_product(self):
        d = failing_access(); p = d['products'][0]; p['http_status'] = 403
        for check in p['access_checks']: check['status'] = 403
        with self.assertRaises(AuditError): prepare(d)

    def test_zero_findings_keep_coverage_gaps(self):
        d = fixture(); d['coverage']['discovery_complete'] = False
        d['coverage']['limitations'].append('还有目录分页未读。')
        for p in d['products']:
            p.update(review_status='pending', http_status=None, access_checks=[], issues=[])
        r = prepare(d)
        self.assertEqual(r['summary']['pending'], 2)
        self.assertEqual(r['summary']['issues'], 0)
        self.assertFalse(r['coverage']['discovery_complete'])


class ProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path == '/old':
                    self.send_response(301); self.send_header('Location', '/ok'); self.end_headers(); return
                code = 404 if self.path == '/gone' else 403 if self.path == '/blocked' else 200
                self.send_response(code); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
                self.wfile.write(b'<html><title>Demo</title><h1>Product <span>A</span></h1><a href="/ok">Current</a></html>')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_live_redirect_and_body_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            a = probe(self.base + '/old', folder, delay=0)['attempts'][0]
            self.assertEqual(a['status'], 200)
            self.assertEqual(a['final_url'], self.base + '/ok')
            self.assertEqual(a['redirects'][0]['status'], 301)
            self.assertEqual(a['h1'], 'Product A')
            self.assertIsNone(a['body_matches_product'])
            self.assertTrue((Path(folder) / a['body_file']).exists())

    def test_404_has_bounded_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            a = probe(self.base + '/gone', folder, delay=0)['attempts']
            self.assertEqual([x['status'] for x in a], [404, 404])

    def test_403_is_recorded_without_aggressive_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            a = probe(self.base + '/blocked', folder, delay=0)['attempts']
            self.assertEqual([x['status'] for x in a], [403])

    def test_size_limit_leaves_a_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            a = probe(self.base + '/ok', folder, delay=0, max_bytes=10, retries=0)['attempts'][0]
            self.assertIn('error', a)
            self.assertNotIn('body_file', a)


if __name__ == '__main__':
    unittest.main(verbosity=2)
