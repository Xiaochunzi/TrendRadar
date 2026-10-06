"""A compact Bark notification per event, with a clickable original-source URL."""
import json
from urllib.parse import urlsplit
import requests


def bark_target(url):
    p = urlsplit(url)
    path = p.path.strip('/').split('/')
    if p.scheme != 'https' or not p.hostname or p.username or p.password or not path[0] or p.query or p.fragment:
        raise ValueError('BARK_URL 必须是 https://服务器/device_key 格式')
    return f'https://{p.netloc}/push', path[0]


def payload_for(event, device_key):
    body = (f"发现：{event.finding}\n证据：{event.evidence_quote}\n意义：{event.why_it_matters}\n"
            f"判断更新（推断）：{event.judgment_update}\n局限：{event.limitations}\n"
            f"日期：{event.primary.published_at[:10]} · 置信度 {event.confidence:.0%}\n"
            f"依据：{event.primary.evidence_scope}，点击查看原文。")
    payload = {'device_key': device_key, 'title': 'AI 前沿 · '+event.event_title[:80],
               'body': body, 'url': event.primary.url, 'group': 'AI Frontier', 'isArchive': 1}
    if len(json.dumps({**payload, 'body': ''}, ensure_ascii=False).encode()) > 2800:
        raise RuntimeError('通知链接或配置过长，无法生成 Bark 消息')
    # Leave headroom for APNs/server metadata and measure escaped JSON, not characters.
    while len(json.dumps(payload, ensure_ascii=False).encode()) > 3000:
        payload['body'] = payload['body'][:-50]
    return payload


def send_bark(event, bark_url, post=None):
    endpoint, key = bark_target(bark_url)
    try:
        response = (post or requests.post)(endpoint, json=payload_for(event, key), timeout=20, allow_redirects=False)
        if response.status_code != 200 or response.json().get('code') != 200:
            raise RuntimeError('Bark 服务未确认接收')
    except (requests.RequestException, ValueError) as exc:
        # Never echo request exceptions or response bodies; those may contain the key.
        raise RuntimeError('Bark 请求失败；设备地址与响应内容已隐藏') from None
