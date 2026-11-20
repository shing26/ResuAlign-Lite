# ADR-0070：职位大厅列表轻投影与详情按需加载

- 状态：已采纳（2026-11-20）
- 关联：ADR-0069（单一职位页）、#168

## 背景

合并后的 `#/jobs` 列表与详情共用同一个 `GET /api/jobs?limit=500` 响应。
真实库 432 条岗位时响应 **5,994,155 bytes**，服务端约 **2.39s**；前端首张
岗位卡约 **3127ms**。cProfile 显示 432 条中 219 条执行
`compute_match_signals`，`_prematch_for` 累计 **1.648s**，占请求总耗时
**90%+**。用户打开职位页时，大部分时间花在列表根本不需要的 JD 全文、
diffs、草稿与逐条词表扫描上。

## 决策

1. **新增可选查询参数 `GET /api/jobs?view=full|summary`，默认 `full`。**
   - `full` 保持既有响应形状，不删除字段；
   - `summary` 只返回列表/看板卡所需字段，禁止返回 `jd_text`、`diffs`、
     `invalid_diffs`、`jd_profile`、`gap_report`、`draft`、`final_draft`、
     `eval_score`、`custom_prompt`、`prematch`。
2. **摘要保留派生提示，避免前端退化**：
   - `jd_excerpt`：JD 前 500 字，仅用于客户端关键词补搜与整页 HTML/JSON
     残留识别；详情仍只认完整 `jd_text`；
   - `audience`：服务端用完整 JD 计算 `campus|experienced`，保证校园/社招
     筛选不因摘录截断而失真；
   - `has_jd_profile` 与 `profile_skills`：保留看板技术栈与「待对齐」徽标。
3. **摘要跳过批量 `prematch`。** 该字段是信息性提示，单岗位详情仍返回；
   列表不再为 432 条逐条跑 60 组正则。
4. **详情按需加载。** 工作台列表请求 `view=summary`；选中岗位或深链时才
   请求 `GET /api/jobs/{id}`，并按 `job_id` 缓存在内存。加载中、失败与重试
   都有可见状态。
5. **后退/前进不重拉。** 浏览器后退只关闭详情，复用已加载摘要；详情已
   缓存时前进不重新请求详情。
6. **顶部岗位快速选择器同步使用 `view=summary`。** 它只渲染 id/title/
   company，不应在每次页面启动时拖取最近 100 条的 JD 正文。
7. **`state.jobs` 允许存放摘要。** 需要完整字段的入口（编辑、详情、追加
   投递）先调用 `GET /api/jobs/{id}`，不得把摘要冒充完整对象。

## 后果

- 真实库摘要响应降至 **1,111,717 bytes**，5 次服务端耗时中位 **0.353s**；
- 移动端 390×844 首卡热态中位约 **0.97s**（4 次：1.150 / 0.960 / 0.956 /
  0.986s），桌面 1440×900 **1.09s**；
- 列表/看板首次渲染不再等待 `/api/dashboard` 与词表；后两者到达后只补充
  指标与状态标签；
- 列表/看板卡暂不显示 `prematch` 词表命中徽标，打开详情后可见；
- 客户端实时搜索只覆盖标题/公司/城市/职能/职级/标签与 JD 前 500 字；
  服务端 `search` 参数仍在首次加载与深链时搜索完整 JD。

## 备选与不选

- **只做前端分页**：网络仍传 6MB，服务端仍跑 1.6s prematch，不解决根因；
- **默认把 `/api/jobs` 改成摘要**：会破坏其他调用方对 `jd_text`/`diffs` 的
  既有假设；新增可选参数是向后兼容的最小改动；
- **摘要继续带 `prematch`**：实测占请求 90% 时间，且只是信息性徽标；
- **把摘要永久写回 `state.jobs` 当完整对象**：编辑表单会静默丢 JD 正文。

## 验证

```powershell
$env:PYTHONPATH='D:\ResuAlign-Lite\src'
python -m pytest tests/api/test_job_api.py tests/api/test_match_score.py tests/contracts/test_contract.py -q
node --test --test-concurrency=1 tests/frontend/*.test.mjs tests/frontend/dom/*.test.mjs
python scripts/qa_dogfooder.py
```

- API：新增 `view` 参数后 OpenAPI 快照有意更新；默认 `full` 字段不变；
- 前端：621 passed / 0 failed；
- QA 狗食走查：0 findings；
- 真实浏览器：390×844 与 1440×900 控制台 0 error，详情只请求 1 次，
  后退不新增列表请求，前进到已缓存详情不新增详情请求。
