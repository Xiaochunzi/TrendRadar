"""Strict LLM output boundary: IDs, evidence quotes, score ranges and hard gates."""
import json
import math
import re
from .models import TOPICS, Signal, parse_date

METRICS = ('significance', 'evidence', 'novelty', 'trajectory')


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Invalid score')
    return float(value)


def validate(raw, candidates, config):
    if not isinstance(raw, dict) or not isinstance(raw.get('events'), list):
        raise ValueError('Expected events array')
    by_id = {c.id: c for c in candidates}
    result, used = [], set()
    for event in raw['events']:
        if not isinstance(event, dict):
            raise ValueError('Invalid event')
        if event.get('decision') == 'reject':
            continue
        ids = event.get('member_ids')
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i in by_id for i in ids):
            raise ValueError('Unknown member ID')
        if len(set(ids)) != len(ids) or used.intersection(ids):
            raise ValueError('Repeated member ID')
        used.update(ids)
        primary_id = event.get('primary_id')
        evidence_id = event.get('evidence_member_id')
        if primary_id not in ids or evidence_id not in ids:
            raise ValueError('Invalid primary/evidence member')
        topic, decision = event.get('topic'), event.get('decision')
        if topic not in TOPICS or decision not in ('significant', 'watch'):
            raise ValueError('Invalid topic/decision')
        scores = {m: number(event.get('scores', {}).get(m)) for m in METRICS}
        confidence = number(event.get('confidence'))
        fields = ('event_title', 'finding', 'evidence_quote', 'why_it_matters', 'judgment_update', 'limitations')
        if not all(isinstance(event.get(f), str) and 0 < len(event[f].strip()) <= 1500 for f in fields):
            raise ValueError('Missing or excessive text')
        quote = event['evidence_quote'].strip()
        # Quotes must exist verbatim in actual source input, never generated evidence.
        evidence = by_id[evidence_id]
        if len(quote) < 12 or quote not in evidence.text:
            raise ValueError('Ungrounded evidence quote')
        # Reject numeric findings that introduce numbers absent from supplied evidence text.
        stated_numbers = set(re.findall(r'\d+(?:[.,]\d+)*', event['finding']))
        source_numbers = set(re.findall(r'\d+(?:[.,]\d+)*', evidence.text))
        if not stated_numbers.issubset(source_numbers):
            raise ValueError('Ungrounded numerical finding')
        primary = by_id[primary_id]
        # Secondary-only and undated findings cannot become confirmed frontline news.
        significant = (decision == 'significant' and primary.source_kind == 'primary'
                       and evidence.source_kind == 'primary' and parse_date(primary.published_at)
                       and scores['evidence'] >= config.get('min_evidence', .75)
                       and scores['significance'] >= config.get('min_significance', .8)
                       and scores['trajectory'] >= config.get('min_trajectory', .7)
                       and scores['novelty'] >= config.get('min_novelty', .6)
                       and confidence >= config.get('min_confidence', .75))
        result.append(Signal(event['event_title'], topic, [by_id[i] for i in ids], primary, scores,
                             confidence, event['finding'], quote, evidence_id, event['why_it_matters'],
                             event['judgment_update'], event['limitations'], 'significant' if significant else 'watch'))
    return result


def rank(candidates, client, prompt, config, history):
    events = []
    size = config.get('batch_size', 20)
    for start in range(0, len(candidates), size):
        batch = candidates[start:start + size]
        payload = {'candidates': [c.to_dict() for c in batch], 'recently_delivered': history[-30:]}
        response = client.chat([{'role': 'system', 'content': prompt},
                                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}], temperature=.2)
        text = response.strip()
        if text.startswith('```') and text.endswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        events.extend(validate(json.loads(text), batch, config))
    return events


def select(events, state, config, now):
    ranked = sorted(events, key=lambda e: e.priority, reverse=True)
    selected, watch, topics, keys = [], [], {}, set()
    remaining = max(0, min(3, config.get('max_signals', 3)) - state.delivered_count(now.date().isoformat()))
    for event in ranked:
        if event.key in keys or state.was_delivered(event):
            continue
        keys.add(event.key)
        if event.decision == 'significant' and len(selected) < remaining:
            if topics.get(event.topic, 0) >= config.get('max_per_topic', 2):
                if len(watch) < min(5, config.get('max_watch', 3)):
                    watch.append(event)
                continue
            selected.append(event)
            topics[event.topic] = topics.get(event.topic, 0) + 1
        elif len(watch) < min(5, config.get('max_watch', 3)):
            watch.append(event)
    return selected, watch
