# Tickets 2.1: Workbench Polish

## T2.1-1 设置页热切换模型

状态：已完成

- 后端：`config.RUNTIME_LLM_OVERRIDE`、settings store 持久化
  `llm_provider` / `llm_model`、`PUT /api/settings` 与 `POST /api/settings/reset`。
- 前端：删除评估权重与薪资参照表表单，新增 LLM 模型表单与运行状态卡片。
- 测试：`tests/test_settings_routes.py`。

## T2.1-2 JD 智能分析真实化

状态：已完成

- 后端：`POST /api/workbench/session/{session_id}/analyze`，
  自动从 session 的 `selected_resume_id` 读取简历做差距分析。
- 前端：工作台打开自动解析 JD，支持手动重试、失败提示。
- 测试：`tests/test_workbench_session.py`。

## T2.1-3 工作台岗位切换与任务恢复

状态：已完成

- 工作台顶部岗位下拉切换；空工作台岗位选择；
  返回工作台自动恢复轮询与对齐进度。

## T2.1-4 简历解析效率

状态：已完成

- docx 表格提取、txt GB18030 兜底、文本归一化、
  上传接口返回结构化 `sections`。
- 测试：`tests/test_parser.py`。

## T2.1-5 岗位抓取准确度

状态：已完成

- 公司名清理、JSON-LD / OpenGraph 元数据增强、
  SSR JSON 正文兜底、飞书 HTML 字段清理。
- 测试：`tests/test_crawler_hardening.py`。

## T2.1-6 对齐画布进度与错误反馈

状态：已完成

- 提交任务立即显示进度条与阶段；失败显示错误并允许重试。
