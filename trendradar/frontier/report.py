from html import escape
import json
from pathlib import Path


def markdown(selected, watch, health, now, demo=False, collect_only=False):
    lines = ['# AI 前沿雷达', '', now.strftime('%Y-%m-%d %H:%M %Z'), '']
    if demo:
        lines += ['**演示预览：以下均为虚构测试案例，不代表真实研究进展。**', '']
    failed = [s['source'] for s in health if not s['ok']]
    lines += [f"来源覆盖：{len(health)-len(failed)}/{len(health)} 成功。", '']
    if failed:
        lines += ['**覆盖不完整：** '+ '、'.join(failed)+'。不能据此判断今天没有重要进展。', '']
    if collect_only:
        lines += ['只完成来源采集；尚未接入 AI 模型，未进行重要性筛选。', '']
    elif not selected:
        lines += ['本次没有可推送的新信号（可能未达门槛、已推送或当天名额已用完）。', '']
    for heading, entries in [('值得读', selected), ('继续观察', watch)]:
        if not entries:
            continue
        lines += ['## '+heading, '']
        for e in entries:
            lines += ['### '+e.event_title, '',
                      f'名称：{e.primary.title}', f'日期：{e.primary.published_at[:10] or "来源未提供"}',
                      f'来源：{e.primary.source} · {e.primary.url}', '',
                      '发现：'+e.finding, '', '证据原文：'+e.evidence_quote, '',
                      '为什么重要：'+e.why_it_matters, '', '判断更新（推断）：'+e.judgment_update, '',
                      '局限：'+e.limitations, '',
                      f'依据范围：{e.primary.evidence_scope} · 编辑判断置信度：{e.confidence:.0%}', '']
    return '\n'.join(lines)


def html_report(selected, watch, health, now, demo=False, collect_only=False):
    def p(label, value):
        return f'<p><b>{label}</b>{escape(value)}</p>'
    cards = []
    for heading, entries in [('值得读', selected), ('继续观察', watch)]:
        if entries:
            cards.append(f'<h2>{heading}</h2>')
        for e in entries:
            cards.append('<article><span class="tag">'+escape(e.topic)+' · '+f'{e.confidence:.0%}'+'</span>'
                         +'<h3>'+escape(e.event_title)+'</h3>'
                         +p('名称：', e.primary.title)
                         +p('日期：', e.primary.published_at[:10] or '来源未提供')
                         +p('发现：', e.finding)+'<blockquote>'+escape(e.evidence_quote)+'</blockquote>'
                         +p('意义：', e.why_it_matters)+p('判断更新（推断）：', e.judgment_update)
                         +p('局限：', e.limitations)
                         +'<footer>'+escape(e.primary.source+' · '+e.primary.evidence_scope)
                         +' · <a rel="noopener noreferrer" href="'+escape(e.primary.url, quote=True)+'">阅读原文 ↗</a></footer></article>')
    failed = [s['source'] for s in health if not s['ok']]
    banner = '<p class="notice">演示预览 · 虚构测试案例，不代表真实研究进展</p>' if demo else ''
    if collect_only:
        banner += '<p class="notice">只完成来源采集；等待接入 AI 模型进行筛选。</p>'
    if failed:
        banner += '<p class="notice">覆盖不完整：'+escape('、'.join(failed))+'</p>'
    if not selected and not collect_only:
        banner += '<p>本次没有可推送的新信号。</p>'
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 前沿雷达</title><style>
body{margin:0;background:#f4f6fa;color:#17243c;font:16px/1.7 system-ui,-apple-system,sans-serif}
main{max-width:760px;margin:auto;padding:28px 18px 50px}h1{font-size:30px;letter-spacing:-1px;margin:0}h2{margin-top:30px;font-size:20px}
h3{font-size:21px;line-height:1.5;margin:12px 0}article{background:white;border:1px solid #e0e6ef;border-radius:16px;padding:22px;margin:16px 0}
p{margin:12px 0}b{color:#30415c}.tag{font-size:12px;background:#eaf1ff;color:#305d9d;border-radius:20px;padding:4px 10px}
blockquote{margin:16px 0;border-left:3px solid #6390cd;padding:12px 16px;background:#f5f8fd;font-size:14px;overflow-wrap:anywhere}
footer,.meta{font-size:13px;color:#64748b}a{color:#275f9e}.notice{background:#fff3d6;padding:12px;border-radius:10px}
</style><main><header><div class="meta">FRONTIER SIGNAL</div><h1>AI 前沿雷达</h1><p class="meta">'''+now.strftime('%Y-%m-%d %H:%M')+f' · 来源 {len(health)-len(failed)}/{len(health)}</p></header>'+banner+''.join(cards)+'</main></html>'


def write_reports(output, selected, watch, health, now, demo=False, collect_only=False):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    (out/'latest.md').write_text(markdown(selected, watch, health, now, demo, collect_only), encoding='utf-8')
    (out/'latest.html').write_text(html_report(selected, watch, health, now, demo, collect_only), encoding='utf-8')
    (out/'latest.json').write_text(json.dumps({'demo': demo, 'collect_only': collect_only, 'generated_at': now.isoformat(),
                                             'sources': health, 'signals': [e.to_dict() for e in selected],
                                             'watch': [e.to_dict() for e in watch]}, ensure_ascii=False, indent=2), encoding='utf-8')
