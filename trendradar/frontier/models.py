from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TOPICS = {'rsi', 'agents', 'scaling', 'measurement', 'compute', 'alignment', 'wildcard'}


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
        raise ValueError('Invalid article URL')
    host = p.hostname.lower().removeprefix('www.')
    path = p.path.rstrip('/') or '/'
    if host in ('arxiv.org', 'export.arxiv.org'):
        host = 'arxiv.org'
        path = re.sub(r'^/pdf/', '/abs/', path).removesuffix('.pdf')
        path = re.sub(r'v\d+$', '', path)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                             if not k.lower().startswith('utm_') and k.lower() not in ('ref', 'si', 'fbclid', 'gclid')))
    # Preserve non-default ports, as they may identify a different origin.
    netloc = host if p.port in (None, 80, 443) else f'{host}:{p.port}'
    return urlunsplit(('https', netloc, path, query, ''))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def normalized_title(title: str) -> str:
    return re.sub(r'[^\w]', '', title.casefold())


def parse_date(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


@dataclass
class Candidate:
    id: str
    title: str
    url: str
    source: str
    source_kind: str
    published_at: str = ''
    text: str = ''
    evidence_scope: str = 'RSS 摘要'
    aliases: list[str] = field(default_factory=list)

    @classmethod
    def make(cls, title, url, source, source_kind, published_at='', text='', evidence_scope='RSS 摘要'):
        url = canonical_url(url)
        return cls(digest(url), title, url, source, source_kind, published_at, text, evidence_scope, [url])

    def to_dict(self):
        return asdict(self)


@dataclass
class Signal:
    event_title: str
    topic: str
    members: list[Candidate]
    primary: Candidate
    scores: dict[str, float]
    confidence: float
    finding: str
    evidence_quote: str
    evidence_member_id: str
    why_it_matters: str
    judgment_update: str
    limitations: str
    decision: str

    @property
    def key(self):
        return digest(normalized_title(self.event_title))

    @property
    def priority(self):
        s = self.scores
        return 0.3*s['significance'] + 0.25*s['trajectory'] + 0.2*s['evidence'] + 0.15*s['novelty'] + 0.1*self.confidence

    def to_dict(self):
        result = asdict(self)
        result.update(key=self.key, priority=round(self.priority, 3))
        return result
