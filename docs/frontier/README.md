# AI 前沿雷达：第一版

基于 TrendRadar 6.10.0，上游提交 `792bcc3928b1617bba09df34989fd5675c159b86`。
保留上游 GPL-3.0 许可与原有功能，新增独立入口，不把通用热榜混入 AI 报告。

## 第一版做什么

- 采集一手研究源和专家博客，复用 TrendRadar 的 RSSFetcher、RSSParser、AIClient。
- URL 规范化（包含 arXiv 版本）、相同/近乎相同标题合并、来源轮询预算，避免大 feed 占满候选。
- 模型结合标题与摘要（或官方网页正文节选）聚类事件并评估重要性、证据、新颖性、趋势影响。
- 代码再执行硬门槛：必须有一手来源、发表日期、逐字可核验的证据原文，且四项评分与置信度达标。
- RSI、长程 Agent、Scaling、能力测量、计算成本、Alignment，以及可能改变范式的 wildcard。
- 每个上海自然日最多推送 3 个新事件，同主题最多 2 条；观察内容只出现在报告中。
- Markdown、手机可读 HTML、结构化 JSON 三种报告。每条含名称、日期、证据、意义、推断、局限、原文。
- Bark 接收确认后才写 SQLite 记录；预览不消费记录，失败可重试。空结果不发送通知。
- 来源失败写入报告，所有来源失败则运行失败，不把失败误报为“无进展”。

## 本地最快看效果

需要 Python 3.12+。在仓库根目录：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-frontier.txt
python -m trendradar.frontier --demo
```

打开 `output/frontier-demo/latest.html`。**演示数据全部虚构**，只展示布局和筛选流程，不表示真实研究结果。

采集真实来源，不需要模型密钥：

```bash
python -m trendradar.frontier --collect-only
python -m trendradar.frontier --check-sources
```

真实筛选复用上游 LiteLLM 接口：配置环境变量 `AI_API_KEY`，可选 `AI_MODEL` 和 `AI_API_BASE`。
默认模型配置与上游一致，`deepseek/deepseek-chat`；可以替换成你已有的兼容模型。
**ChatGPT Plus 订阅不在这里充当 API 密钥。** 当前交付没有替你购买或开通 API。

```bash
python -m trendradar.frontier
```

默认只生成报告。运行前验证密钥配置；模型调用失败、非法 JSON 或虚构证据会使运行失败，不回退到低质量关键词消息。

## 最快手机推送：Bark

选它是因为 iPhone 只需装 App、打开通知、提供一个设备推送地址，不需要维护服务器、注册机器人或配置邮件 SMTP。

1. 从 App Store 安装官方 Bark（项目：<https://github.com/Finb/Bark>），打开通知权限。
2. 在 App 首页复制**基础设备地址**，形如 `https://api.day.app/<device_key>`。
3. 把它设置为环境变量 `BARK_URL`。不要写到仓库、报告、截图或日志中；不要在聊天里贴设备地址。
4. 已有模型密钥后执行：

```bash
python -m trendradar.frontier --push
```

收到的每条通知包含：中文发现、证据、意义、推断、局限、日期。点击直接打开一手原文；在 Bark 中可以查看通知存档。
通知按实际 JSON 字节控制在 3000 字节内，留出 APNs 元数据空间。长内容会截短，完整报告保留在 `latest.html` / `latest.md`。
这是最少步骤的版本：不需要先部署一个阅读网站。后续可以把点击目标改成每日报告页面。

## 不开服务器：GitHub Actions

新增 `.github/workflows/frontier.yml`；默认**不开启定时任务**，只允许你手动运行。建议先使用 `collect_only` 验证来源。

Fork 并把开发分支合入你的默认分支后，在仓库 Settings → Secrets and variables → Actions 设置：

| 类型 | 名称 | 内容 |
|---|---|---|
| Secret | `AI_API_KEY` | 模型服务的 API 密钥 |
| Secret | `BARK_URL` | Bark 基础设备地址 |
| Variable（可选） | `AI_MODEL` | LiteLLM provider/model 标识 |
| Variable（可选） | `AI_API_BASE` | 兼容服务的基础地址 |
| Variable（可选） | `FRONTIER_ENABLED` | 确定启用每天推送后才设为 `true` |

Actions → **AI Frontier Radar** → Run workflow：第一次不选 `push`，查看 `frontier-report` artifact；确认后再选 `push`。
定时启用后默认上海时间约 **08:07**，GitHub 可能排队延迟，不是准点服务。
每次从最新 `frontier-state` artifact 恢复历史，再上传接收记录；部分失败也上传已成功记录。
状态保留 90 天。手工删除历史 artifact 或历史过期后，去重会从空状态重建。
上游通用热榜 workflow 的定时触发已在此分支移除，防止 fork 后跑出无关热榜；仍保留手动运行。

## 验证与当前边界

```bash
python -m unittest discover -s tests/frontier -v
```

测试覆盖证据虚构、无一手来源、无日期、非法分数、来源公平预算、日期过滤、去重、当天上限、失败重试、通知长度、HTML 转义和无密钥行为。

- 当前主要依据 RSS 摘要；网页适配器提供官方正文节选。**没有声称已深读所有 PDF 或 independently reproduce 实验。**
- 逐字证据校验验证文本来源，不保证论文结论正确；编辑判断仍需人工阅读关键原文。
- 事件语义聚类在每批候选内进行；跨批主要靠 URL、稳定事件名和近乎相同标题去重。复杂转载的跨批语义合并还可能漏掉。
- 120 个候选、每批 20 条为默认成本上限。第一次可能会评估近 7 天内容，不保证覆盖全世界所有研究。
- 只有摘要的二手报道不会进入显著信号。跨来源转载也不自动等于独立验证。
- API 费用由所选模型服务产生，未测实际每日费用；可以调低候选上限。
- Bark 确认表示服务接收，不证明 iOS 最终展示。网络超时若发生在服务接收之后，重试仍可能重复，不能承诺严格 exactly-once。
- 当前没有真实 API 密钥与设备地址；采集、离线逻辑与模拟推送可以验证，真实模型与手机接收要在接入后各跑一次。

## 项目文件

- `config/frontier.yaml`：来源、阈值、预算、输出。
- `config/frontier_prompt.txt`：中文编辑规则与结构化输出契约。
- `trendradar/frontier/`：独立运行入口、采集、筛选、记录、报告和通知。
- `.github/workflows/frontier.yml`：可手动运行、可后续启用的每日流程。
- `docs/frontier/example.html`：有明显虚构标记的演示报告。

第一版接入目标：先收到一条内容正确、点得开原文的手机通知，再决定是否增加每日网页、周报和更深的论文阅读。

## 远端保存

远端 Fork：`https://github.com/Xiaochunzi/TrendRadar`，开发分支：`feat/ai-frontier-radar`。源码包仍可独立使用；如需在其他账号创建 Fork，在自己的终端安装 GitHub CLI，完成 `gh auth login` 后，运行 `bash scripts/fork-and-push-frontier.sh`。脚本会自动为源码包建立上游 Git 工作区，不会修改上游仓库。
