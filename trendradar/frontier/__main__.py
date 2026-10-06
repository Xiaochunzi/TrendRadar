import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
import yaml

from .models import Candidate
from .notify import bark_target, send_bark
from .ranker import rank, select
from .report import write_reports
from .sources import collect, prepare, validate_sources
from .state import State


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(config.get('sources'), list):
        raise ValueError('配置缺少 sources')
    for name in ('max_candidates', 'batch_size', 'max_age_days', 'retention_days', 'fetch_timeout', 'max_per_topic'):
        if name in config and (type(config[name]) is not int or config[name] < 1):
            raise ValueError(f'{name} 必须是正整数')
    for s in config['sources']:
        if not all(k in s for k in ('id', 'name', 'url', 'kind')) or s['kind'] not in ('primary', 'expert', 'discovery'):
            raise ValueError('来源配置无效')
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description='AI Frontier Radar: evidence-first digest and Bark push')
    parser.add_argument('--config', default='config/frontier.yaml')
    parser.add_argument('--output')
    parser.add_argument('--state')
    parser.add_argument('--demo', action='store_true', help='虚构样例预览；不会调用真实模型或推送')
    parser.add_argument('--collect-only', action='store_true', help='采集真实来源，不调用模型')
    parser.add_argument('--check-sources', action='store_true')
    parser.add_argument('--input', help='离线候选 JSON 数组，仍需真实模型筛选')
    parser.add_argument('--push', action='store_true', help='显式发送到 BARK_URL')
    args = parser.parse_args(argv)
    if args.demo and (args.push or args.input or args.collect_only or args.check_sources):
        parser.error('--demo 不能与真实输入、采集、检查或推送混用')
    if args.collect_only and args.push:
        parser.error('--collect-only 不能推送')
    state = None
    output = None
    try:
        config = load_config(args.config)
        now = datetime.now(ZoneInfo(config.get('timezone', 'Asia/Shanghai')))
        if args.check_sources:
            statuses = validate_sources(config)
            print(json.dumps(statuses, ensure_ascii=False, indent=2))
            return int(any(not s['ok'] for s in statuses))
        output = args.output or ('output/frontier-demo' if args.demo else config['output_dir'])
        if args.push:
            if not os.environ.get('BARK_URL'):
                raise ValueError('推送需要设置 BARK_URL')
            bark_target(os.environ['BARK_URL'])
        client = None
        if not args.demo and not args.collect_only:
            # Fail before collection/spend when credentials have not been configured.
            from trendradar.ai.client import AIClient
            ai = config.get('ai', {})
            client = AIClient({'MODEL': os.environ.get('AI_MODEL') or ai.get('model', ''),
                               'API_KEY': os.environ.get('AI_API_KEY', ''),
                               'API_BASE': os.environ.get('AI_API_BASE', ''),
                               'TIMEOUT': ai.get('timeout', 120), 'MAX_TOKENS': ai.get('max_tokens', 7000),
                               'NUM_RETRIES': 1})
            valid, error = client.validate_config()
            if not valid:
                raise ValueError(error)
        if args.demo:
            from .demo import candidates as demo_candidates, DemoClient
            items, health, client = demo_candidates(now), [{'source': '虚构演示来源', 'ok': True}], DemoClient()
        elif args.input:
            items = [Candidate.make(**c) for c in json.loads(Path(args.input).read_text(encoding='utf-8'))]
            items = prepare(items, config, now)
            health = [{'source': '离线输入（未进行网络覆盖验证）', 'ok': True}]
        else:
            items, health = collect(config, now)
        Path(output).mkdir(parents=True, exist_ok=True)
        # A replayable input contains only known Candidate.make arguments.
        (Path(output)/'candidates.json').write_text(json.dumps([
            {'title': c.title, 'url': c.url, 'source': c.source, 'source_kind': c.source_kind,
             'published_at': c.published_at, 'text': c.text, 'evidence_scope': c.evidence_scope} for c in items
        ], ensure_ascii=False, indent=2), encoding='utf-8')
        if args.collect_only:
            write_reports(output, [], [], health, now, collect_only=True)
            print(f'采集 {len(items)} 个候选；未评分、未推送。报告：{output}/latest.html')
            return int(not any(s['ok'] for s in health))
        state_path = args.state or (str(Path(output)/'state.sqlite3') if args.demo else config['state_path'])
        state = State(state_path, now, config.get('retention_days', 90))
        if health and not any(s['ok'] for s in health):
            write_reports(output, [], [], health, now)
            raise RuntimeError('所有信息源均失败，不能生成无进展日报')
        prompt = Path(config['prompt_file']).read_text(encoding='utf-8')
        events = rank(items, client, prompt, config, state.history())
        selected, watch = select(events, state, config, now)
        write_reports(output, selected, watch, health, now, demo=args.demo)
        if not args.push:
            print(f'预览：{len(selected)} 条值得读，{len(watch)} 条观察；未发送、未消耗去重记录。报告：{output}/latest.html')
            return 0
        failures = 0
        for event in selected:
            try:
                send_bark(event, os.environ['BARK_URL'])
                state.record(event, now)
                print('Bark 已接收 1 条；已记录去重。')
            except RuntimeError as exc:
                failures += 1
                print(str(exc), file=sys.stderr)
        print(f'本次推送 {len(selected)-failures} 条，失败 {failures} 条。')
        return int(bool(failures))
    except Exception as exc:
        # Provider/library exceptions may echo secrets or URLs. Do not expose arbitrary messages.
        safe = str(exc) if type(exc) in (ValueError, RuntimeError) and not any(s in str(exc) for s in ('http', 'key=')) else type(exc).__name__
        print('运行失败：'+safe, file=sys.stderr)
        if output:
            # Do not leave an earlier report looking like a successful current run.
            Path(output).mkdir(parents=True, exist_ok=True)
            (Path(output)/'latest.md').write_text('# AI 前沿雷达\n\n本次运行失败，未生成新的研究判断。请查看运行日志。\n', encoding='utf-8')
            (Path(output)/'latest.html').write_text('<!doctype html><meta charset="utf-8"><title>运行失败</title><p>本次运行失败，未生成新的研究判断。请查看运行日志。</p>', encoding='utf-8')
            (Path(output)/'latest.json').write_text(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}), encoding='utf-8')
        return 1
    finally:
        if state:
            state.close()


if __name__ == '__main__':
    raise SystemExit(main())
