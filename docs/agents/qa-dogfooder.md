# QA Dogfooder Agent（ResuAlign 实例）

> 本文件是通用 QA Agent（[qa-agent.md](./qa-agent.md)）在 ResuAlign-Lite
> 的实例化，保留项目专属上下文、harness 与产物约定；角色定位、体验维度、
> 问题去模糊化与报告模板以通用文档为准。

## 1. 项目上下文

- Web UI：`http://127.0.0.1:8000`，hash 路由：
  `#/dashboard`、`#/workspace/<jobId>`、`#/jobs`、`#/resume`、
  `#/today`、`#/settings`。
- 数据：本地 SQLite（`data/jobs.db`），个人模式默认租户 `local`。
- 核心流程：简历诊断 → JD 画像/差距分析 → 简历对齐（Diff）→ 可选评估。
- 禁止污染：真实用户数据的破坏性用例必须通过隔离环境执行
  （`scripts/qa_dogfooder.py` 会自动启动 fake LLM + 临时 DB 的独立实例）。

## 2. 重点体验维度

沿用通用五维，本项目重点覆盖：

1. 主路径：dashboard → 新建/诊断简历 → 岗位库粘贴 JD → 工作台对齐 →
   定稿导出 → 今日待办 → 设置主题。
2. 极端与异常：空库、超长 JD、HTML/脚本注入、无效深链、无效抓取 URL。
3. 状态一致性：新建简历 F5、诊断结果刷新、命令面板深链、重复提交幂等。
4. 响应式：1440x900 与 390x844 下的导航可点、无横向溢出。
5. 静默失败：所有路由的控制台错误、请求失败、未捕获异常。

## 3. 运行方式

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python scripts\qa_dogfooder.py
```

Harness 行为：

- 启动 fake LLM（`.scratch/phase-20/fake_llm.py`）与真实 App，使用临时
  SQLite，端口随机，结束后自动清理。
- 使用 Playwright（headless Chromium）覆盖五个维度，截图与控制台日志写入
  `.scratch/qa/`。
- 输出 `findings.json` 与终端摘要；每个 finding 都带严重级别、复现步骤、
  实际/预期和疑似根因。

## 4. 产出物归属

- 报告落地为 `docs/qa-dogfood-report-*.md`，模板沿用通用 QA Agent 的报告
  模板。
- 需要工程跟进的问题按 `docs/agents/triage-labels.md` 分诊，通过
  `gh` 写入 GitHub Issues（见 `docs/agents/issue-tracker.md`）。
