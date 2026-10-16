#!/usr/bin/env python3
"""Record live public GET evidence. No product classification or content verdicts."""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo


def http_url(value):
    p = urllib.parse.urlsplit(value.strip())
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Use an HTTP(S) URL without embedded credentials.')
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path or '/', p.query, ''))


class Extract(HTMLParser):
    def __init__(self, url):
        super().__init__()
        self.url, self.active, self.anchor = url, None, None
        self.title, self.h1, self.links, self.canonical = [], [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('title', 'h1'):
            self.active = tag
        if tag == 'a' and a.get('href'):
            self.anchor = {'url': urllib.parse.urljoin(self.url, a['href']), 'text': ''}
        if tag == 'link' and 'canonical' in a.get('rel', '').lower().split():
            self.canonical = urllib.parse.urljoin(self.url, a.get('href', ''))

    def handle_data(self, data):
        if self.active == 'title':
            self.title.append(data)
        if self.active == 'h1':
            self.h1.append(data)
        if self.anchor is not None:
            self.anchor['text'] += data

    def handle_endtag(self, tag):
        if tag == self.active:
            self.active = None
        if tag == 'a' and self.anchor is not None:
            self.anchor['text'] = ' '.join(self.anchor['text'].split())
            self.links.append(self.anchor)
            self.anchor = None


class Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.chain = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        http_url(newurl)
        self.chain.append({'status': code, 'from': req.full_url, 'to': newurl})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe(url, out, *, timeout=25, max_bytes=4_000_000, timezone='UTC', retries=1, delay=.5):
    url = http_url(url)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    attempts = []
    for index in range(retries + 1):
        now = datetime.now(ZoneInfo(timezone)).isoformat()
        record = {'url': url, 'final_url': url, 'checked_at': now, 'live': True,
                  'status': None, 'body_matches_product': None}
        redirects = Redirects()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ProductContentAudit/1.0',
                'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
            try:
                response = urllib.request.build_opener(redirects).open(req, timeout=timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                record.update(status=response.code, final_url=response.geturl(),
                              content_type=response.headers.get('Content-Type', ''))
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ValueError('Response exceeds max-bytes; body not saved or audited.')
                digest = hashlib.sha256(raw).hexdigest()
                filename = f'{hashlib.sha256(url.encode()).hexdigest()[:12]}-{digest[:12]}.html'
                (out / filename).write_bytes(raw)
                record.update(body_file=filename, bytes=len(raw), sha256=digest)
                if 'html' in record['content_type'].lower():
                    charset = response.headers.get_content_charset() or 'utf-8'
                    parser = Extract(record['final_url'])
                    parser.feed(raw.decode(charset, errors='replace'))
                    record.update(title=' '.join(' '.join(parser.title).split()),
                                  h1=' '.join(' '.join(parser.h1).split()),
                                  canonical=parser.canonical, links=parser.links)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, LookupError) as error:
            record['error'] = str(error)
        record['redirects'] = redirects.chain
        attempts.append(record)
        time.sleep(delay)
        if not (record.get('error') or record['status'] in (404, 410, 429) or
                (record['status'] is not None and record['status'] >= 500)):
            break
    return {'url': url, 'attempts': attempts}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--url', action='append', default=[])
    ap.add_argument('--url-file', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--timezone', default='UTC')
    ap.add_argument('--timeout', type=float, default=25)
    ap.add_argument('--max-bytes', type=int, default=4_000_000)
    ap.add_argument('--retries', type=int, choices=(0, 1), default=1)
    ap.add_argument('--delay', type=float, default=.5)
    args = ap.parse_args()
    if args.timeout <= 0 or args.max_bytes <= 0 or args.delay < 0:
        ap.error('timeout/max-bytes must be positive; delay must be nonnegative')
    urls = args.url + (args.url_file.read_text(encoding='utf-8').splitlines() if args.url_file else [])
    urls = list(dict.fromkeys(http_url(u) for u in urls if u.strip() and not u.lstrip().startswith('#')))
    if not urls:
        ap.error('Supply --url or --url-file')
    results = []
    for url in urls:
        item = probe(url, args.out, timeout=args.timeout, max_bytes=args.max_bytes,
                     timezone=args.timezone, retries=args.retries, delay=args.delay)
        results.append(item)
        (args.out / 'probes.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'url': url, 'statuses': [a['status'] for a in item['attempts']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
