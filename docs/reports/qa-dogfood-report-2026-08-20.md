# QA 狗粮与缺陷基线报告（2026-08-20）

_运行方式: `docs/agents/qa-dogfooder.md`（fake LLM + 临时 DB 隔离实例）_

## 1. 基线测试

| 套件 | 结果 |
| --- | --- |
| 后端 pytest | 1007 passed, 7 skipped |
| 前端 node（happy-dom） | 460 passed |
| 浏览器 E2E（Playwright） | 7 passed |
| QA 狗粮路由巡检 | 0 findings |

## 2. QA 狗粮路由巡检结果

按五个维度（主路径 / 极端异常 / 状态一致 / 响应式 / 静默失败）在 1440x900 与
390x844 下巡检全部 hash 路由与工作台流程，`findings.json` 为空。控制台仅出现
路由切换时的 SSE/会话轮询 `ERR_ABORTED`（浏览器主动中断，属正常 SPA 行为）。
截图落地 `.scratch/qa/`（desktop-* / mobile-* 共 14 张）。

## 3. 已复查的 08-19 评审项（均已在 HEAD 修复，仅作核对）

- `parser.py` `_BULLET_RE` 已不含 `o/O/0`，`Objective` 等行首不再被误当 bullet（P1 已修）。
- `tailor.py` `_METRIC_HINT_RE` 的 ASCII token（qps/tps/rt/pv/uv/roi）已带 `\b` 词边界（P2 已修）。
- `format.js` `interviewCheatSheetHtml` 的 `topic` 已在第 2296 行的追问文案中被使用（P3 已修）。

## 4. 本轮真实待跟进项

### [P2] 后端基础差 Windows 非 UTF-8 区域（本轮已修）

- 位置：`tests/test_e2e.py`
- 现象：`read_text()` 用区域默认编码（GBK）读 UTF-8 报告，`UnicodeDecodeError`
- 修法：读报告显式 `encoding="utf-8"`（已修复并验证）

### [P1-P2] Provider 稳定性（专项文档，逐阶段推进）

见 `docs/llm-provider-stability-analysis.md` 与 `docs/adr/0032-…`。其中
「一键连通性测试」「模型分级路由」已实现；剩余缺口按 Phase 1-5 排期，Phase 1
（sanitizer）本轮已落地。

## 5. 分诊建议

| 项 | 建议 label |
| --- | --- |
| Provider 稳定性 Phase 2-5 | `ready-for-agent`（按阶段拆分 issue） |
| 扩展 QA 覆盖（长流程对齐/投递/面试闭环） | `needs-triage` |
