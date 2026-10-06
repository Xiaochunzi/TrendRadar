"""Explicitly fictional fixtures. Never mix this provider with live candidates."""
import json
from .models import Candidate


def candidates(now):
    return [Candidate.make('DEMO: Research Agent Evaluation', 'https://example.com/demo-agent',
                           '演示研究机构（虚构）', 'primary', now.isoformat(),
                           'DEMO ONLY. In a fictional held-out evaluation of 40 tasks, the agent completed 26 tasks. No independent replication is available.', '虚构测试摘要'),
            Candidate.make('DEMO: Compute Study', 'https://example.com/demo-compute',
                           '演示研究机构（虚构）', 'primary', now.isoformat(),
                           'DEMO ONLY. The fictional experiment reduced compute by 30 percent at the same evaluation score. Only one workload was measured.', '虚构测试摘要')]


class DemoClient:
    def chat(self, messages, **kwargs):
        items = json.loads(messages[-1]['content'])['candidates']
        events = []
        for c in items:
            agent = 'agent' in c['url']
            events.append({'event_title': '演示：研究 Agent 的泛化测评' if agent else '演示：相同得分下的计算成本下降',
                           'topic': 'rsi' if agent else 'compute', 'decision': 'significant',
                           'member_ids': [c['id']], 'primary_id': c['id'], 'evidence_member_id': c['id'],
                           'scores': {'significance': .9, 'evidence': .85, 'novelty': .8, 'trajectory': .85},
                           'confidence': .85,
                           'finding': '虚构演示：40 项留出任务完成 26 项，用于展示证据格式。' if agent else '虚构演示：在相同得分下，计算量下降 30%。',
                           'evidence_quote': c['text'],
                           'why_it_matters': '这段文字用于演示如何解释实验的意义，不构成现实研究结论。',
                           'judgment_update': '真实使用时，只在实验支持的任务与预算范围内更新判断。',
                           'limitations': '全部数据与机构均为虚构。真实报告还需交代基线、任务范围和独立复现情况。'})
        return json.dumps({'events': events}, ensure_ascii=False)
