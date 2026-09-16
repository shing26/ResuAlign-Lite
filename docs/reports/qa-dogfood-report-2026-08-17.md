# 产品体验与缺陷报告 - ResuAlign 3.0 MVP（2026-08-17）

## 1. 体验总览

* 体验角色：新用户 / 深度创作者 / 破坏性测试者
* 健康指数：🟢 仅体验调优
* 核心体感：主路径可完整跑通；本轮 QA 最终 0 条 finding，前端 443 用例、
  E2E 7 用例、后端 953 用例全部通过。

## 2. 环境与执行方式

* 环境：Windows PowerShell / Python 3.11.9 / Playwright 1.61 / headless
  Chromium
* 隔离：`scripts/qa_dogfooder.py` 自动启动 fake LLM
  （`.scratch/phase-20/fake_llm.py`）与真实 App，使用临时 SQLite、随机端口，
  结束后清理，不触碰真实 `data/jobs.db`

```powershell
$env:PYTHONPATH = "D:\ResuAlign-Lite\src"
python scripts\qa_dogfooder.py
python tests\e2e\run_e2e.py
node --test tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs
python -X utf8 -m ruff check src/resualign tests scripts
python -X utf8 -m pytest tests/ -q
```

## 3. 覆盖范围

* 路由：`#/dashboard`、`#/workspace/<id>`、`#/jobs`、`#/today`、
  `#/resume`、`#/settings`、未知路由、无效深链
* 五维：主路径与认知负荷、极端与异常边界、状态一致性与持久化、
  响应式与视觉、控制台与静默失败
* MVP 专项：四维匹配分落库与排序、今日待办、canonical 导出
  （PDF/Markdown/JSON）、成本护栏 429、在线备份与恢复服务端口守卫、
  390px 移动端主导航可点

## 4. 缺陷与体验问题清单

最终 `findings.json` 为 0 条。本轮过程中发现并处理的问题如下：

### 🟢 [QA-01] 移动端导航 settings 不可点击

* 严重级别：P1（已修复）
* 问题类别：视觉适配
* 复现环境：Chromium 390x844，访问 `#/dashboard`
* 现象：`settings` 按钮被横向滚动推出视口，中心点无法命中
* 处理：窄屏主导航改为紧凑单行，6 个入口均在首屏可点

### 🟢 [QA-02] 匹配分探针误报“未落库”

* 严重级别：P2（探针修正，非产品缺陷）
* 问题类别：测试脚本
* 现象：未选择主简历并完成对齐时，岗位本来就不应生成匹配分
* 处理：QA 探针改为走“创建主简历 → 运行 workbench → 等待评分”的真实链路

### 🟢 [QA-03] E2E 仍断言已移除的会话内导出

* 严重级别：P2（测试契约修正）
* 问题类别：回归测试
* 现象：`export-align-markdown` 已随 MVP-09 移除
* 处理：E2E 改为断言 canonical `export-final-draft-md` 的定稿内容与采纳项

## 5. 产品决策确认

* Message / 求职信 / Cover Letter / 内推话术 / 自动发送确认排除：不保留
  入口、模板或自动发送；跟进提醒仅保留 Webhook / 邮件可选出口。
* 铁律继续成立：改写可溯源、数据本机 SQLite、AI 调用有每日预算护栏。

## 6. 产物与结论

* `.scratch/qa/findings.json`：0 findings
* `.scratch/qa/desktop-*.png` / `mobile-*.png`：路由截图
* `.scratch/qa/console-all.log`：控制台与请求日志
* E2E：`7 passed`
* 前端：`443 pass / 0 fail`
* Ruff：`All checks passed`
* 后端：`953 passed, 7 skipped`

结论：ResuAlign 3.0 MVP 主路径、异常降级、状态持久化、响应式与静默失败
检查均通过，可以进入交付验收。
