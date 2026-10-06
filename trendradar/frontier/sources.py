"""Reuse upstream RSSFetcher/parser; make failures and evidence scope explicit."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from difflib import SequenceMatcher

from trendradar.crawler.rss import RSSFeedConfig, RSSFetcher, RSSParser
from .models import Candidate, normalized_title, parse_date


def fetch_one(source, timeout):
    if source.get('type') == 'page-list':
        from .pages import fetch_pages
        return fetch_pages(source, timeout)
    fetcher = RSSFetcher([RSSFeedConfig(source['id'], source['name'], source['url'],
                                      max_items=source.get('max_items', 30))], timeout=timeout)
    # The upstream parser defaults to 500 characters; retain more evidence here.
    fetcher.parser = RSSParser(max_summary_length=4000)
    try:
        items, error = fetcher.fetch_feed(fetcher.feeds[0])
        if error:
            return [], {'source': source['name'], 'ok': False, 'error': '抓取或解析失败'}
        if not items:
            return [], {'source': source['name'], 'ok': False, 'error': '未解析到条目（可能不是有效 feed）'}
        candidates = []
        for item in items:
            try:
                candidates.append(Candidate.make(item.title, item.url, source['name'], source['kind'],
                                                 item.published_at, item.summary))
            except ValueError:
                continue
        return candidates, {'source': source['name'], 'ok': bool(candidates), 'items': len(candidates)}
    finally:
        fetcher.session.close()


def collect(config, now):
    enabled = [s for s in config['sources'] if s.get('enabled', True)]
    candidates, health = [], []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(enabled)))) as pool:
        for items, status in pool.map(lambda s: fetch_one(s, config.get('fetch_timeout', 20)), enabled):
            candidates.extend(items)
            health.append(status)
    return prepare(candidates, config, now), health


def prepare(candidates, config, now):
    """Freshness is about publication, never crawl time; undated items are watch-only."""
    cutoff = now - timedelta(days=config.get('max_age_days', 7))
    unique = []
    for item in sorted(candidates, key=lambda c: (c.source_kind != 'primary', not bool(c.text))):
        published = parse_date(item.published_at)
        if published and (published < cutoff or published > now + timedelta(minutes=5)):
            continue
        title = normalized_title(item.title)
        duplicate = next((c for c in unique if c.url == item.url or
                          (len(title) >= 12 and title == normalized_title(c.title)) or
                          (len(title) > 30 and SequenceMatcher(None, title, normalized_title(c.title)).ratio() >= .98)), None)
        if duplicate:
            duplicate.aliases = sorted(set(duplicate.aliases + item.aliases + [item.url]))
            if len(item.text) > len(duplicate.text) and item.source_kind == duplicate.source_kind:
                duplicate.text = item.text
            continue
        unique.append(replace(item, aliases=list(item.aliases)))
    # Round robin sources prevents a large arXiv feed from eating the entire LLM budget.
    groups = {}
    for c in unique:
        groups.setdefault(c.source, []).append(c)
    result = []
    while groups and len(result) < config.get('max_candidates', 120):
        for source in list(groups):
            result.append(groups[source].pop(0))
            if not groups[source]:
                del groups[source]
            if len(result) >= config.get('max_candidates', 120):
                break
    return result


def validate_sources(config):
    """Check content, not merely HTTP status: a 200 HTML error page is a failure."""
    enabled = [s for s in config['sources'] if s.get('enabled', True)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [status for _, status in pool.map(lambda s: fetch_one(s, config.get('fetch_timeout', 20)), enabled)]
