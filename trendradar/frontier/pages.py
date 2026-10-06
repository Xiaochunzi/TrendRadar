"""Small official-site adapters for publishers without a working native feed."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit
import requests
from .models import Candidate


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.meta = {}
        self.main_depth = 0
        self.skip = 0
        self.parts = []
        self.body_parts = []
        self.in_body = False
        self.article_started = False
        self.title_parts = []
        self.in_title = False
        self.dates = []
        self.in_jsonld = False
        self.jsonld = []
        self.jsonld_dates = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        if tag == 'meta' and a.get('content'):
            self.meta[a.get('property') or a.get('name', '')] = a['content']
        if tag == 'time' and a.get('datetime'):
            self.dates.append(a['datetime'])
        if tag == 'main':
            self.main_depth += 1
        if tag == 'body':
            self.in_body = True
        if tag == 'h1' and self.in_body:
            self.article_started = True
        if tag in ('script', 'style', 'nav', 'footer'):
            self.skip += 1
        if tag == 'script' and a.get('type') == 'application/ld+json':
            self.in_jsonld = True
            self.jsonld = []
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_jsonld:
            self.in_jsonld = False
            try:
                data = json.loads(''.join(self.jsonld))
                nodes = data if isinstance(data, list) else [data]
                for node in nodes:
                    if isinstance(node, dict) and '@graph' in node:
                        nodes.extend(node['@graph'])
                    if isinstance(node, dict) and isinstance(node.get('datePublished'), str):
                        self.jsonld_dates.append(node['datePublished'])
            except (ValueError, TypeError):
                pass
        if tag == 'main':
            self.main_depth = max(0, self.main_depth-1)
        if tag == 'body':
            self.in_body = False
        if tag in ('script', 'style', 'nav', 'footer'):
            self.skip = max(0, self.skip-1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, text):
        if self.in_jsonld:
            self.jsonld.append(text)
        if self.in_title:
            self.title_parts.append(text)
        if self.main_depth and not self.skip and text.strip():
            self.parts.append(text.strip())
        if self.in_body and self.article_started and not self.skip and text.strip():
            self.body_parts.append(text.strip())

    @property
    def title(self):
        return self.meta.get('og:title', '') or ' '.join(self.title_parts)

    @property
    def published(self):
        # Explicit metadata only. An arbitrary <time> could be an update date.
        return self.meta.get('article:published_time', '') or next(iter(self.jsonld_dates), '')

    @property
    def text(self):
        # Epoch's pages have no semantic <main>; start at the article's first h1.
        return re.sub(r'\s+', ' ', ' '.join(self.parts or self.body_parts))[:20000]


def get_page(url, timeout):
    with requests.get(url, timeout=timeout, stream=True,
                      headers={'User-Agent': 'TrendRadar/6.10 AI Frontier Reader'}) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 6_000_000:
                raise ValueError('Page exceeds adapter size limit')
            chunks.append(chunk)
        content = b''.join(chunks).decode(response.encoding or 'utf-8', errors='replace')
    parser = PageParser()
    parser.feed(content)
    return parser


def listing_urls(page, base, pattern, limit):
    origin = urlsplit(base).netloc
    urls = []
    for href in page.links:
        url = urljoin(base, href)
        p = urlsplit(url)
        if p.scheme == 'https' and p.netloc == origin and re.fullmatch(pattern, p.path) and not p.query:
            if url not in urls:
                urls.append(url)
    return urls[:limit]


def fetch_pages(source, timeout):
    try:
        listing = get_page(source['url'], timeout)
        urls = listing_urls(listing, source['url'], source['path_pattern'], source.get('max_items', 10))
        if not urls:
            return [], {'source': source['name'], 'ok': False, 'error': '官方列表未解析出文章链接'}
        def read(url):
            try:
                page = get_page(url, timeout)
                if not page.title or len(page.text) < 100:
                    return None
                return Candidate.make(page.title.strip(), url, source['name'], source['kind'],
                                      page.published, page.text, '官方网页正文节选（最多 20000 字符，未读取附件 PDF）')
            except (requests.RequestException, ValueError):
                return None
        with ThreadPoolExecutor(max_workers=3) as pool:
            items = [c for c in pool.map(read, urls) if c]
        return items, {'source': source['name'], 'ok': bool(items), 'items': len(items),
                       'failed_articles': len(urls)-len(items),
                       'undated_articles': sum(not c.published_at for c in items)}
    except (requests.RequestException, ValueError):
        return [], {'source': source['name'], 'ok': False, 'error': '官方网页采集失败'}
