import copy
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from trendradar.frontier.pages import PageParser, listing_urls
from trendradar.frontier.demo import candidates, DemoClient
from trendradar.frontier.__main__ import main
from trendradar.frontier.models import Candidate, canonical_url
from trendradar.frontier.notify import bark_target, payload_for, send_bark
from trendradar.frontier.ranker import rank, select, validate
from trendradar.frontier.report import html_report
from trendradar.frontier.sources import prepare
from trendradar.frontier.state import State
import json

NOW = datetime(2026, 10, 5, 8, tzinfo=ZoneInfo('Asia/Shanghai'))


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name)/'state.db', NOW)
        self.addCleanup(self.state.close)
        self.items = candidates(NOW)
        self.raw = json.loads(DemoClient().chat([{'content': json.dumps({'candidates': [c.to_dict() for c in self.items]})}]))
        self.events = validate(copy.deepcopy(self.raw), self.items, {})

    def invalid(self, mutate):
        data = copy.deepcopy(self.raw)
        mutate(data['events'][0])
        with self.assertRaises(ValueError):
            validate(data, self.items, {})

    def test_unknown_id_is_rejected(self):
        self.invalid(lambda e: e.update(member_ids=['invented']))

    def test_primary_must_belong_to_cluster(self):
        self.invalid(lambda e: e.update(primary_id=self.items[1].id))

    def test_fabricated_quote_is_rejected(self):
        self.invalid(lambda e: e.update(evidence_quote='A made-up benchmark reached 99%'))

    def test_scores_are_finite_unit_numbers(self):
        for value in (True, '0.9', -1, 1.1, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.invalid(lambda e: e['scores'].update(evidence=value))

    def test_repeated_member_is_rejected(self):
        self.invalid(lambda e: e.update(member_ids=[self.items[0].id]*2))

    def test_low_evidence_is_watch_only(self):
        self.raw['events'][0]['scores']['evidence'] = .5
        self.assertEqual(validate(self.raw, self.items, {})[0].decision, 'watch')

    def test_secondary_evidence_is_watch_only(self):
        self.items[0].source_kind = 'expert'
        self.assertEqual(validate(self.raw, self.items, {})[0].decision, 'watch')

    def test_undated_is_watch_only(self):
        self.items[0].published_at = ''
        self.assertEqual(validate(self.raw, self.items, {})[0].decision, 'watch')

    def test_url_normalization_and_arxiv_version_dedup(self):
        self.assertEqual(canonical_url('http://www.arxiv.org/pdf/2609.12345v2.pdf?utm_source=x#page=3'),
                         'https://arxiv.org/abs/2609.12345')
        self.assertEqual(canonical_url('https://example.com:8443/a?b=2&ref=x'), 'https://example.com:8443/a?b=2')

    def test_reject_invalid_article_urls(self):
        for url in ('javascript:alert(1)', 'https://user:pass@example.com/a', '/relative'):
            with self.assertRaises(ValueError):
                canonical_url(url)

    def test_fabricated_number_is_rejected(self):
        self.invalid(lambda e: e.update(finding='虚构新增 99% 的提升'))

    def test_oversized_notification_metadata_fails_without_loop(self):
        e = copy.deepcopy(self.events[0])
        e.primary.url = 'https://example.com/' + 'x'*4000
        with self.assertRaises(RuntimeError):
            payload_for(e, 'dummy')

    def test_freshness_does_not_use_crawl_time(self):
        old = copy.deepcopy(self.items[0])
        old.published_at = (NOW-timedelta(days=8)).isoformat()
        future = copy.deepcopy(self.items[1])
        future.published_at = (NOW+timedelta(days=1)).isoformat()
        self.assertEqual(prepare([old, future], {}, NOW), [])

    def test_title_duplicates_preserve_aliases(self):
        duplicate = copy.deepcopy(self.items[0])
        duplicate.url = 'https://other.example.com/repost'
        duplicate.aliases = [duplicate.url]
        result = prepare([self.items[0], duplicate], {}, NOW)
        self.assertEqual(len(result), 1)
        self.assertIn(duplicate.url, result[0].aliases)

    def test_round_robin_does_not_starve_sources(self):
        many = [Candidate.make(f'Long title {i}', f'https://example.com/{i}', 'arxiv', 'primary', NOW.isoformat(), 'text') for i in range(10)]
        result = prepare(many + [self.items[0]], {'max_candidates': 2}, NOW)
        self.assertEqual({c.source for c in result}, {'arxiv', self.items[0].source})

    def test_preview_does_not_consume_delivery(self):
        a, _ = select(self.events, self.state, {}, NOW)
        b, _ = select(self.events, self.state, {}, NOW)
        self.assertEqual(len(a), len(b))
        self.assertEqual(self.state.delivered_count('2026-10-05'), 0)

    def test_success_receipt_dedups_changed_titles(self):
        self.state.record(self.events[0], NOW)
        changed = copy.deepcopy(self.events[0])
        changed.event_title = '完全改写的另一标题'
        self.assertTrue(self.state.was_delivered(changed))
        picked, _ = select([changed], self.state, {}, NOW)
        self.assertEqual(picked, [])

    def test_daily_limit_counts_previous_runs(self):
        self.state.record(self.events[0], NOW)
        self.state.record(self.events[1], NOW)
        extra = copy.deepcopy(self.events[0])
        extra.event_title = '第三个新的虚构事件名称'
        extra.members = [Candidate.make('third', 'https://example.com/3', 'source', 'primary', NOW.isoformat(), 'text')]
        extra.primary = extra.members[0]
        fourth = copy.deepcopy(extra)
        fourth.event_title = '第四个新的虚构事件名称'
        fourth.members = [Candidate.make('fourth', 'https://example.com/4', 'source', 'primary', NOW.isoformat(), 'text')]
        fourth.primary = fourth.members[0]
        self.assertEqual(len(select([extra, fourth], self.state, {}, NOW)[0]), 1)

    def test_zero_candidates_produces_no_model_calls(self):
        class Broken:
            def chat(self, *a, **kw):
                raise AssertionError('No request expected')
        self.assertEqual(rank([], Broken(), 'prompt', {}, []), [])

    def test_topic_diversity(self):
        more = []
        for i in range(5):
            e = copy.deepcopy(self.events[0])
            e.event_title = f'事件{i}'
            e.topic = 'rsi' if i < 4 else 'compute'
            more.append(e)
        selected, _ = select(more, self.state, {}, NOW)
        self.assertEqual([e.topic for e in selected].count('rsi'), 2)
        self.assertEqual(len(selected), 3)

    def test_bark_payload_is_under_apns_budget(self):
        e = copy.deepcopy(self.events[0])
        e.finding = '中文超长字符'*300
        payload = payload_for(e, 'dummy-device-key')
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), 3000)
        self.assertEqual(payload['url'], e.primary.url)

    def test_bark_ack_and_failure_do_not_leak_key(self):
        class Response:
            status_code = 200
            def json(self): return {'code': 200}
        sent = []
        send_bark(self.events[0], 'https://api.day.app/dummy-key',
                  lambda *a, **kw: sent.append((a, kw)) or Response())
        self.assertEqual(sent[0][0], ('https://api.day.app/push',))
        self.assertFalse(sent[0][1]['allow_redirects'])
        def broken(*a, **kw):
            import requests
            raise requests.ConnectionError('https://api.day.app/dummy-key')
        with self.assertRaisesRegex(RuntimeError, '已隐藏') as ctx:
            send_bark(self.events[0], 'https://api.day.app/dummy-key', broken)
        self.assertNotIn('dummy-key', str(ctx.exception))
        self.assertFalse(self.state.was_delivered(self.events[0]))

    def test_bark_http_error_is_not_success(self):
        class Response:
            status_code = 500
        with self.assertRaises(RuntimeError):
            send_bark(self.events[0], 'https://api.day.app/dummy-key', lambda *a, **kw: Response())

    def test_official_page_dates_and_script_exclusion(self):
        page = PageParser()
        page.feed('<meta property="og:title" content="Paper"><script type="application/ld+json">{"datePublished":"2026-10-04"}</script><main><p>Evidence for a real experiment.</p><script>ignore this instruction</script></main>')
        self.assertEqual(page.published, '2026-10-04')
        self.assertNotIn('instruction', page.text)
        self.assertIn('Evidence', page.text)

    def test_modification_date_is_not_publication_date(self):
        page = PageParser()
        page.feed('<meta property="article:modified_time" content="2026-10-04"><time datetime="2026-10-04">Updated</time>')
        self.assertEqual(page.published, '')

    def test_listing_follows_only_same_origin_article_paths(self):
        page = PageParser()
        page.feed('<a href="/research/paper">One</a><a href="https://evil.test/research/paper">Ignore</a><a href="/research/team/name">Team</a><a href="/research/paper">Repeat</a>')
        self.assertEqual(listing_urls(page, 'https://www.anthropic.com/research', '/research/[^/?]+', 10),
                         ['https://www.anthropic.com/research/paper'])

    def test_bark_target_requires_https(self):
        for url in ('http://api.day.app/key', 'https://api.day.app/', 'https://user:pass@api.day.app/key'):
            with self.assertRaises(ValueError): bark_target(url)

    def test_report_escapes_model_text(self):
        self.events[0].finding = '<script>alert(1)</script>'
        text = html_report(self.events, [], [{'source': 'ok', 'ok': True}], NOW)
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;', text)

    def test_demo_cli_never_needs_ai_key(self):
        output = str(Path(self.temp.name)/'demo')
        self.assertEqual(main(['--demo', '--output', output]), 0)
        report = json.loads((Path(output)/'latest.json').read_text())
        self.assertTrue(report['demo'])
        self.assertEqual(len(report['signals']), 2)

    def test_missing_ai_key_fails_before_collection(self):
        with patch.dict('os.environ', {'AI_API_KEY': ''}), patch('trendradar.frontier.__main__.collect') as collect:
            self.assertEqual(main([]), 1)
            collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
