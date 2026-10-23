# 0062 — 编辑器默认墙钟放宽到 150 秒

- **状态**: 已采纳
- **日期**: 2026-10-20
- **关联**: issue #165、#159；ADR-0059；ADR-0056

## 背景

编辑器墙钟是每次 POST 的硬截止，不是整次调用的累计预算。上一轮 Reolink
编辑器调用有 2/3 在 90 秒撞线；后续腾讯 #1 单发已达 81.9 秒，距离默认
90 秒只剩约 8 秒。当前 3072-token 起步、length 翻倍到 6144 的路径在慢节点
上需要更大余量。

## 决策

1. `_ROLE_TIMEOUT_DEFAULTS["editor"]` 从 `90.0` 调整为 `150.0` 秒。
2. `RESUALIGN_ROLE_TIMEOUT_EDITOR` 环境变量覆盖仍然优先；该值同时作为
   编辑器客户端 timeout 与单次 POST wall-clock deadline。
3. 前端在 `/api/settings/status` 未返回时使用同一默认值，展示区间变为
   `45–150 秒`；运行时仍以后端返回值为准。
4. 不改变 `profiler=75`、`gap_analyzer=60`、`diagnose=45`、
   `evaluator=60`。最坏单发墙钟估算为 `45+75+150=270s`，仍远低于
   `RESUALIGN_JOB_MAX_RUNTIME_S=1800`。

## 后果

- 慢节点完成一次完整编辑器输出的概率提高，尤其覆盖 schema 修复后的单次
  重试和大输入。
- 失败路径的最长用户等待增加，但 watchdog、连接超时、熔断和环境变量覆盖
  仍提供上限与人工调节手段。
- 这是时间预算修正，不是质量门放宽；内容级 provenance 校验和
  `#164/#165` 的 allowlist 收紧保持不变。
