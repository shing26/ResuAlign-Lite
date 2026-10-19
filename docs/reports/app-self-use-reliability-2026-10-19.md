# app 自用可靠性验证（ADR-0059 P0）

日期：2026-10-19

## 结论

**未通过，且比首轮结论更严重。** 首轮报告把腾讯用例判为「候选被真实性检查
拦下」；本轮拿到原始模型报文后更正为：那些 JD 关键词经由 gap report 的
`missing_keywords` 进入 allowlist 语料，**内容级校验会放行，编造内容被判成
`verified` / 可用**——是假通过，不是误杀。

已落地的修复（#163）在 app 侧把「技能清单新增条目」拦成 invalid，堵住假通过。
修复后单次重跑：**3 例 usable_diffs 全为 0**（首轮是 0 / 1 / 2）。随后在
2026-10-19 13:43–13:56 用当前可用的 `nvidia/nemotron-3-super-120b-a12b`
跑 3×3：**9 次中 3 次产出可用建议**（腾讯 1/3、Dida 2/3、Reolink 0/3），
9 次均无基础设施错误。产出仍明显偏向技能清单，Reolink 三轮全部零产出。

**guard 后复测（2026-10-19 17:59–18:10，同一节点、同一 3×3）**：加完
中文缺口术语 guard 与 evaluator 逐条隔离后重跑，**0/9 可用**（腾讯 0/3、
Dida 0/3、Reolink 0/3）。前一轮那 3 个「可用」正是被 allowlist 放行的
编造项（腾讯技能清单新增条目、Dida 技能清单条目），guard 把它们从
`verified` 改判为 `fabricated` 之后，编辑器**没有产出任何有原文支撑的改写**。
即：guard 修掉的是「假通过」，没有修掉「编辑器产不出真建议」。详见第七节。

本轮样本只验证引擎产出可靠性，没有执行采纳、保存定稿、导出或投递记录，
因此 app 自用验证线仍为 **0 / 3**；新三步工作台继续保持 feature flag 关闭。

## 输入

- 主简历：`134ebf1e78c844fc94c33ad255bc4f74`
  （`陈振成 AI 应用开发 / Agent 研发工程师（Java + Python 双栈）`，3287 chars）
- 模型：`nvidia/nemotron-3-super-120b-a12b`（`llm_nodes` 中的 active node，
  `disable_thinking=1`）
- 验证实例：隔离数据目录（复制 `data/jobs.db` 到 `.scratch/p0-159-rerun/data`）
  + 进程内 `engine.run`；不写 `data/jobs.db`，不触碰 8000

| 用例 | library_job_id | 源状态 | 说明 |
| --- | --- | --- | --- |
| 腾讯后台开发 | `bcb5d7bb9a91428eb974e47b92874d17` | `applied` | 唯一有投递标记的用例 |
| Dida 后端开发 | `20d47a3e5c3f4dc5b91b18daa41d403a` | `draft` | 真实完整 JD，provisional |
| Reolink web 后端 | `093a9116119a40e2bd84f6cebce6cd32` | `draft` | 真实完整 JD，provisional |

## 一、根因更正：allowlist 让「JD 关键词直灌」假通过

首轮报告依据的是隔离实例的终态计数，没有留下原始报文。本轮用同一份简历 +
库中腾讯 gap report 重放编辑器调用（脚本 `.scratch/p0_163_repro.py`，单次
editor 调用，无 DB 写入），拿到原始输出：

- 模型返回 2 条 `modify` diff，section 都是「专业技能清单」；
- 两条都在原文条目后追加了同一条新技能：
  「系统基础能力：熟悉 Linux 操作系统、TCP/UDP 网络协议基础及进程间通讯
  概念；掌握 Shell 脚本编写与自动化任务；了解负载均衡技术原理及智能运维
  故障预测思路；掌握常用设计模式……」；
- `gate_diff_items` 判定 **usable=2 / invalid=0**。

原因在 `_gap_support_text`：它把 gap report 的 `missing_keywords` 也算进
「JD 允许术语」语料，而 `missing_keywords` 按定义就是「JD 要、简历没有」的
词。于是「把 JD 缺口词写进技能清单」恰好落在放行集合里。

这不是实现走样，而是上游 `true-tailor` 的既定规则：`tests/fixtures/gate`
的 `d8-allowlist-term` / `e6-allowlist-term` 两个场景就锁着「JD 术语可作为
改写素材」，且由 `VENDOR.json` 做字节锁。**改语料语义 = 改上游 gate 规则**，
必须先在 truetailor 落地再同步，因此本轮不动 `gate.py`。

## 二、修复（#163）：编辑器产出约束

两处改动，`gate.py` 与 `tests/fixtures/gate/*` 未动：

1. **提示词契约**（`TAILOR_PROMPT` → `tailor/v3`）：规则 5 由「每个
   missing_keyword 至少被一条 diff 覆盖」改为「只覆盖原文有事实支撑的缺口，
   没有安全改写就不产出该条 diff」；新增规则 8「技能清单/专业技能类章节只能
   改写已有条目，禁止新增条目」。
2. **app 侧产出约束**（`_apply_editor_output_contract`）：`modify`/`add` 命中
   技能章节、且 `proposed` 的条目数多于 `original` 时，降级为
   `provenance_state="fabricated"` 并移入 `invalid_diffs`。整卷编辑器
   （`tailor_resume`）与逐条编辑器（`tailor_resume_map_reduce`）都过这条约束。

约束按**条目数**判定，与 allowlist 语义解耦，所以不需要动上游规则就能堵住
「往技能清单里加条目」。它在 `gate_diff_items` 之外，parity 锁
（`tests/engine/test_gate.py::TestDriftLockParity`）保持原样。

载荷证明（同一输入，`.scratch` 一次性校验）：

```
WITHOUT app-side guard -> usable: 1 invalid: 0
WITH app-side guard   -> usable: 0 invalid: 1
```

回归：`tests/engine/test_tailor.py` 新增 6 例（腾讯形态单条/两条、合法技能
改写、非技能章节不受限、`_skills_entry_growth` 结构判定、prompt 契约）。
后端全量：**1269 passed / 7 skipped**。

## 三、修复后重跑 3 份真实 JD

脚本 `.scratch/p0_159_rerun.py`（隔离数据目录，进程内完整角色管线
diagnose → profiler → gap → editor → evaluator，复用 `alignment_rules`
的终态规则）。原始结果见 `.scratch/p0-159-rerun/results.json`。

| 用例 | 墙钟 | alignment | usable | invalid | 拦截原因 |
| --- | ---: | --- | ---: | ---: | --- |
| 腾讯后台开发 | 40.0s | failed `no_output` | 0 | 1 | 技能清单新增条目 → 产出约束拦截 |
| Dida 后端开发 | 81.0s | failed `no_output` | 0 | 1 | 技能清单新增条目，锚点不可解析 → `missing` |
| Reolink web 后端 | 51.9s | failed `no_output` | 0 | 3 | 1 条产出约束拦截 + 2 条 evaluator 判幻觉整体拦截 |

阶段日志显示 diagnose / profiler / gap / editor / evaluation 均完成，
`tailor_degraded=False`，没有 profiler 超时——首轮的阶段超时确实已修掉。

补充实验：把腾讯用例切到逐条编辑器（`RESUALIGN_BULLET_EDITOR_CLOUD=1`）重跑，
23.2s，结果不变（usable=0，仍是一条技能清单新增条目被拦）。**因此「把云端
默认切到 map-reduce」并不能解决这个问题**，模型在两种编辑器下都会去灌技能清单。

## 四、未通过项

- 单次重跑 3 例 usable_diffs 全为 0；3×3 复跑虽为 3/9 可用，但 Reolink
  0/3，腾讯与 Dida 也只有部分样本可用。编辑器在缺口较大的岗位下仍频繁只
  产出技能清单灌水；被正确拦截后就没有可采纳建议。这是模型质量 + 编辑器
  策略问题，不是超时或 schema 问题。
- 只有 1 份 JD 在库中标记为 `applied`；另 2 份是真实 JD 但投递状态未登记。
- 本轮没有执行定稿保存、导出或投递记录，因此不满足 ADR-0059 的 app 自用
  验证线（0 / 3），不满足 #159 的通过线。
- 「无安全改写」目前仍以 `no_output:` 失败文案呈现（「该岗位存在能力/经验
  缺口，但本轮未产出任何可用改写建议」）。语义上算明确判定，但产品上仍是
  「工具坏了」的读法，需要单独的呈现口径（归 P2 文案，不在 P0 范围）。

## 五、Handoff 与下一步

1. **上游规则（truetailor）**：`missing_keywords` 作为放行术语来源，会让
   「把 JD 缺口词写进技能清单」假通过。app 侧已用条目数约束兜住技能清单这一
   类；更一般的「JD 术语当能力声明」需要上游 gate 规则变更 + fixture，先在
   truetailor 落地再同步（ADR-0041 决定 11 漂移锁）。
2. **P0 未过线 → 不启动 P2**（ADR-0059 决定 3）。新工作台保持 feature flag
   关闭，默认回旧版。
3. 通过线要求作者真实投递过的 3 份 JD；当前只有 1 份，按 #159 约束转
   `needs-info`，等作者补齐输入后再判通过与否。
4. 继续修可靠性的候选方向（需要决策，不在本报告内自行拍板）：换更强/更听话
   的模型节点；或让编辑器在「有缺口但无安全改写」时显式产出该结论，而不是
   沉默到 `no_output`。

## 六、免费节点候选实测（2026-10-19）

### 来源（均为 NVIDIA 一手）

- `https://build.nvidia.com/llms.txt`：「All models offer a free trial tier
  with no credit card required.」；base URL `https://integrate.api.nvidia.com/v1`，
  全部 OpenAI Chat Completions 兼容。
- `https://build.nvidia.com/models.md`（206 条目录，含描述）与用户给的
  `filters=nimType:nim_type_preview` 目录页（24 张卡带 **Free Endpoint** 标）。
- `GET https://integrate.api.nvidia.com/v1/models`：当前 key 可调用 **81** 个
  model id。切换模型只需改节点里的 model 名，key 通用。

预览目录里属于文本对话/推理的：`nemotron-3.5-super-vl-120b-a12b`、
`step-5-preview`、`deepseek-v4.1-flash`、`glm-5-3`（卡上标
**Deprecation in 10d**，别选）、`glm-5-3-flash`、`nemotron-3.5-lightning-30b-a3b`、
`muse-glimmer-30b`、`laguna-xs-2.1`、`diffusiongemma-26b-a4b-it`、
`nemotron-3-ultra-550b-a55b`、`nemotron-3-nano-omni-30b-a3b-reasoning`、
`gemma-4-31b-it`。

### 用真实 editor 调用逐模型实测

脚本 `.scratch/nvidia_model_probe.py`：同一份简历 + 腾讯 gap report，同一套
`TAILOR_PROMPT`/max_tokens/temperature/`response_format=json_object` 与
`thinking:{type:disabled}`（即 app 对 `disable_thinking` 节点发的报文），
**串行**请求保证时延可比。结果见 `.scratch/nvidia_model_probe.json`。

| model | 时延 | finish | 思考被关掉？ | JSON | 结论 |
| --- | ---: | --- | --- | --- | --- |
| `deepseek-ai/deepseek-v4.1-flash` | 54.6s | stop | 是（0 reasoning tokens） | ✅ | **7 条 diff，0 被拦**，全部改写已有条目 |
| `nvidia/nemotron-3-ultra-550b-a55b` | 35.3s | stop | 是 | ✅ | 2 条 diff，1 条把 JD 术语续写进技能行（条目数没变，产出约束拦不到） |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 21.4s / 90.2s | length / 超时 | 是 | ❌ | 3072 被 `sections` 撑爆；按 app 的翻倍重试到 6144 直接撞 90s 死线 |
| `google/gemma-4-31b-it` | 90.2s | 超时 | — | ❌ | 编辑器预算内跑不完 |
| `z-ai/glm-5.3-flash` | 85.9s | length | **否**（3072 全是 reasoning） | ❌ | 不认 `thinking:{type:disabled}`，content 为空 |
| `openai/gpt-oss-20b` | 81.9s | length | **否**（3072 全是 reasoning） | ❌ | 同上 |
| `moonshotai/kimi-k2.6` | 0.4s | 404 | — | ❌ | 列在 `/v1/models` 里，但这个账号 Not found |

注意 `glm-5.3-flash` / `gpt-oss-20b`：app 现在只有一种「关思考」写法
（`thinking:{"type":"disabled"}`），对它们无效。要用这类模型得先按 provider
补不同的关思考字段（`chat_template_kwargs` / `reasoning_effort` 之类）。

### 用候选模型重跑同样 3 份 JD

隔离目录里把 active node 的 model 改成 `deepseek-ai/deepseek-v4.1-flash`
（`P0_MODEL` 覆盖，只改副本），其余不变：

| 用例 | 墙钟 | alignment | usable | invalid | 备注 |
| --- | ---: | --- | ---: | ---: | --- |
| 腾讯后台开发 | 117.8s | **succeeded** | 2 | 2 | 2 条 noop 被 A2 过滤 |
| Dida 后端开发 | 76.3s | **succeeded** | 7 | 0 | 全部为已有条目的改写 |
| Reolink web 后端 | 110.5s | failed `no_output` | 0 | 6 | evaluator 判幻觉 → 整体拦截 |

单次对比：`nemotron-3-super-120b-a12b` 当时是 0 / 0 / 0；换到
`deepseek-v4.1-flash` 后 3 份里 2 份产出可用建议且终态 `succeeded`。
Reolink 那例不是被内容门拦的，是被 LLM-as-judge 的 hallucination 判定整体
拦掉的——那是另一根杠杆（evaluator 自身的模型/阈值），不是同一个问题。

仍未闭合：CJK 的 JD 术语（如「设计模式」）被续写进已有条目时，内容级校验与
条目数约束都拦不到（DeepSeek 这轮也漏了 1 处）。这条仍需上游 gate 规则。

### nemotron 3×3 复跑（2026-10-19 13:43–13:56）

用户决定先切到当前可用的 `nvidia/nemotron-3-super-120b-a12b`，用
`.scratch/p0_159_samples.py`（`P0_SAMPLES=3`）在隔离数据目录跑 3 份 JD × 3。
原始结果见 `.scratch/p0-159-samples/results.json`；本次运行启动时明确打印
`MODEL=nvidia/nemotron-3-super-120b-a12b`。

| 用例 | runs | succeeded | usable 序列 | invalid 序列 | 墙钟中位数 | 备注 |
| --- | ---: | ---: | --- | --- | ---: | --- |
| 腾讯后台开发 | 3 | 1 | 1 / 0 / 0 | 3 / 1 / 1 | 89.3s | 唯一成功样本是 1 条可用改写 |
| Dida 后端开发 | 3 | 2 | 1 / 0 / 1 | 0 / 1 / 0 | 67.4s | 三次中两次各 1 条可用改写 |
| Reolink web 后端 | 3 | 0 | 0 / 0 / 0 | 3 / 3 / 3 | 126.5s | 1 次 evaluator 判幻觉；其余全被拦 |

汇总：**3/9 次 succeeded，3/9 次 usable≥1，0 次基础设施错误**。阶段中位数：
diagnose 1.1s、profiler 9.5s、gap 14.6s、editor 14.6s、evaluation 78.0s；
evaluation 最大 126.7s。免费端点本身可用，但产出稳定性明显不足，且
Reolink 三轮都失败。

**局限**：DeepSeek 仍只有单样本（且端点当前不可用），nemotron 已完成 3×3。
两者样本数不同，不能把 `2/3` 与 `3/9` 直接当成同一统计量比较；但可以确定
「nemotron 可用、产出低且偏技能清单」与「DeepSeek 单次产出更高、端点不可用」
这两个事实。要正式定案，应等 DeepSeek 恢复后也跑 3×3，再记 ADR。

### 采样阻塞：DeepSeek 免费端点不可用（2026-10-19 10:25）

把 live active node 切到 `deepseek-ai/deepseek-v4.1-flash` 后，3×3 样本在
diagnose/profiler 阶段连续超时。为区分模型质量与端点可用性，做了以下探针：

- 同一把 key、同一分钟：`nvidia/nemotron-3-super-120b-a12b` 的 16-token
  请求 **0.9s** 返回；`deepseek-ai/deepseek-v4.1-flash` 的 16-token 请求
  连续 **12/12 次 15s 超时**（每次间隔 30s）。
- 对 DeepSeek 分别去掉 `thinking`、改 `thinking:{type:auto}`、开
  `stream:true`，均在 20s 内拿不到响应；排除了「只是关思考参数导致排队」
  和「非流式聚合慢」两种解释。
- 节点配置本身正确：provider=`nvidia`，base_url=
  `https://integrate.api.nvidia.com/v1`，model=
  `deepseek-ai/deepseek-v4.1-flash`，disable_thinking=1，
  `last_test_status=ok`，`consecutive_failures=0`，`auto_disabled=0`。

因此 DeepSeek 本轮 **没有** 产出可比较的 3×3 `results.json`。后来
`.scratch/p0-159-samples/results.json` 已由 nemotron 3×3 覆盖；该脚本在本次
运行前不写每条记录的 `model` 字段，模型身份以运行日志和本报告为准。后续
脚本已补 `model` 字段。live node 随后按用户决定切到
`nvidia/nemotron-3-super-120b-a12b`；等 DeepSeek 免费端点恢复后，再用
`.scratch/p0_159_samples.py`（`P0_SAMPLES=3`）跑一轮即可形成可比样本。

## 七、后续 P0 补丁（2026-10-19）

在 3×3 结果之后又落了两条 app 侧防线，并补了编辑器契约：

1. **缺口术语兜底**：`_missing_keyword_violation` 在整卷与 map-reduce
   编辑器中检查 `modify`/`add` 的 `proposed`。命中 gap report
   `missing_keywords`、但简历原文无依据的术语 → 降级 `fabricated`，不写回
   `sections`。这堵住中文术语（如「设计模式」）绕过拉丁词内容校验的洞。
2. **evaluator 逐条隔离**：`evaluator/v3` 输出 `hallucinated_diff_ids`；
   `split_verified_diffs` 只隔离被指认的 diff，保留其余已验证建议。若
   evaluator 报幻觉但没有可映射 id，或确定性 provenance 校验发现无 id 的
   坏 diff，仍回退整轮硬阻断。
3. **允许零条安全改写**：`tailor/v3` 的 diffs 范围改为 `0-10`，并明确
   “所有缺口都缺原文事实支撑时返回 `diffs: []` / `sections: {}`”。
   机读终态仍按 ADR-0041 决定 5 呈现 `no_output`，用户文案归 P2。

回归：后端全量 **1276 passed / 7 skipped**。新增测试覆盖整卷与 map-reduce
缺口术语拦截、evaluator diff id 映射、逐条隔离和无 id 回退。issue 评论见
[#163 comment](https://github.com/shing26/ResuAlign-Lite/issues/163#issuecomment-6264399833)。

**上游仍未改**：`truetailor` 的 `missing_keywords` 语义是「简历有证据但
没写出来」，app 的 `gap_analyzer.py` 当前把它当「JD 要、简历没有」的真缺口。
直接改上游 `allowlist_corpus` 会破坏 d8/e6 fixtures 与 skill 契约。需要新
ADR 决定字段拆分（建议 `supported_keywords` vs `unsupported_keywords`），
再改上游、同步 vendor、重跑 parity。决策票见
[#164](https://github.com/shing26/ResuAlign-Lite/issues/164)。

### guard 后 3×3 复测：0/9 可用（2026-10-19 18:10）

脚本 `.scratch/p0_159_samples.py`（`P0_SAMPLES=3`，隔离数据目录，同节点
`nvidia/nemotron-3-super-120b-a12b`）。前一轮结果备份在
`.scratch/p0-159-samples/results-pre-guard.json`，本轮写入 `results.json`。

| 用例 | 样本 usable | 终态 | 拦截/失败形态 |
| --- | --- | --- | --- |
| 腾讯后台开发 | 0 / 0 / 0 | 全 failed `no_output` | #1 技能清单新增条目被拦；#2 #3 编辑器零产出 |
| Dida 后端开发 | 0 / 0 / 0 | 全 failed `no_output` | #1 #2 技能清单新增条目；#3 evaluator 判幻觉，整轮拦截 |
| Reolink web 后端 | 0 / 0 / 0 | #1 #3 基础设施错，其余 failed | 编辑器调用 90s 超时（2/3），#2 tailor 降级 |

**结论（对照前一轮 3/9）**：

1. guard 生效：前一轮 3 个「可用」全部是被 allowlist 放行的编造项，现在
   被正确改判 `fabricated`。假通过 → 真拦截，方向正确。
2. 但**问题没有解决**：编辑器在这些 JD 上**产不出有原文支撑的改写**。
   要么去灌技能清单（被拦），要么在「工作方式/个人特点」类章节写出 evaluator
   判为幻觉的内容（被拦），要么直接返回空 `diffs`（`no_output`）。
   仅靠提示词规则 5/8/9 与 app 侧条目数 guard 不足以让该节点产出真建议。
3. Reolink 编辑器调用 90s 超时 2/3，属基础设施/鲁棒性问题（大输入下编辑器
   墙钟不够），与内容质量分开计。

**下一步方向（需决策，不在本报告内自行拍板）**：把编辑器从「照缺口改写」
改成「照证据改写」——只把**简历原文里有支撑句的缺口**作为改写目标，并明确
告诉编辑器哪些缺口是「无证据的真缺口、不得写进简历」；这需要与 #164 的
字段语义拆分（`supported_keywords` vs `unsupported_keywords`）一起定，因为
「哪些字段进 allowlist」正是假通过的根因。另需单独处理编辑器超时（更大
墙钟或更小载荷）。**在这些落地前，app 自用线保持 0/3，新工作台继续关闭。**

### #164 字段拆分已落地（2026-10-19，ADR-0060）

决策与落地顺序（上游 → 同步 → parity → 编辑器证据化）已按 ADR-0060 执行：

1. **上游 truetailor**（`codex/164-supported-keywords`，commit
   `2b86403`）：`gate.py::allowlist_corpus` 的键列表由 `missing_keywords`
   改为 `supported_keywords`；fixtures 新增 `d11-` / `e8-missing-keyword-not-a-rewrite-source`
   锁定「列在 `missing_keywords` 的词仍被拦成 fabricated」；`SKILL.md` /
   `README.md` / `docs/gate-contract.md` 同步。`python selftest.py`：**19
   场景全过**。
2. **同步 vendor**：`src/resualign/gate.py` + `tests/fixtures/gate/*` 复制
   upstream，`VENDOR.json` 重算哈希、`synced_from=2b864032b6c2`。
3. **parity**：`tests/platform/test_skill_vendor_lock.py` 与
   `tests/engine/test_gate.py::TestDriftLockParity` 全绿（21 passed）。
4. **编辑器证据化**：app 侧 `GapReport` 拆出 `supported_keywords`
   （`gap_analyzer/v3`、`jd-analysis-v4`）；`tailor` 提示词升到 `tailor/v4`，
   明确 `supported_keywords` 是唯一改写方向、`missing_keywords` 是真缺口；
   `_gap_support_text` 与 `_focus_phrases` 都改为读 `supported_keywords`。

回归：后端全量 **1278 passed / 7 skipped**。app 侧新增
`test_gap_support_text_excludes_missing_keywords` 与
`test_analyze_gaps_returns_supported_keywords` 两条锁。

**仍未验证的**：拆分的真实产出效果。`supported_keywords` 需要模型真的按新
契约产出；在这之前，编辑器的可改写语料反而更窄（刻意 fail-closed）。下一
步是用同一 3×3 复测拆分后的产出，并单独处理编辑器 90s 超时。app 自用线
仍为 **0/3**，新工作台继续关闭。

### 拆分后 3×3 复测：2/9（2026-10-19 20:15–20:29）

同节点 `nvidia/nemotron-3-super-120b-a12b`、同 3 份 JD、隔离数据目录
（`.scratch/p0_159_samples.py`，`P0_SAMPLES=3`）。原始结果
`.scratch/p0-159-samples/results.json`（前两轮分别存为
`results-post-guard.json`、`results-pre-guard.json`）。

| 用例 | 三轮 usable | 终态 | 形态 |
| --- | --- | --- | --- |
| 腾讯后台开发 | 1 / 0 / 0 | 1 succeeded | #1 专业技能清单改写通过；#2 #3 技能清单新增条目被拦 |
| Dida 后端开发 | 0 / 3 / 0 | 1 succeeded | #2 三条通过（技能清单+核心项目+工作方式）；#1 #3 evaluator 判幻觉 |
| Reolink web 后端 | 0 / 0 / 0 | 0 succeeded | 三轮全被拦（技能清单新增 + evaluator 判幻觉） |

**2/9 succeeded，0 次基础设施错误**（对照：guard 后 0/9、guard 前 3/9）。
产出从「全是假通过」变成「少量真通过 + 大量诚实拦截」，但 Reolink 仍 0/3。

### 两个新发现（都不在 #164 的修复范围内）

**发现 1：`jd_context` 仍然把整个 JD 灌进 allowlist——假通过的洞没堵死。**
上游 `allowlist_corpus` 的键列表里含 `jd_context`，上游 `SKILL.md` 把它定义为
「one-line summary of what this employer is buying」；app 的
`engine/__init__.py` 却传 `truncate_text(filtered_jd or jd_text, 6000)`——
**整段 JD 原文**。实测（腾讯 JD 609 字符，全部落进 corpus）：

| 词 | 在 corpus | 在简历 |
| --- | --- | --- |
| MySQL | ✅ | ❌ |
| C++ | ✅ | ❌ |
| 算法 | ✅ | ❌ |
| Kubernetes | ❌ | ❌ |

也就是说：JD 里出现、简历没有、又没被 gap analyzer 列进 `missing_keywords`
的词，仍能通过内容级校验。app 侧 guard 只拦 `missing_keywords`，拦不到这一类。
**修复方向**：按上游契约传「一句话摘要」而不是 6000 字 JD 原文；或把
`jd_context` 移出 allowlist 语料。属契约变更，需要决策（同 #164 的处理方式）。

**发现 2：编辑器 90s 墙钟是「每次 POST」而不是「每次调用」。**
`_WallClockDeadlineExceeded` 在 `chat_structured` 的 TransportError 分支里
不重试，所以编辑器**首发超过 90s 即硬失败**（上一轮 Reolink 2/3 就是这么死的，
日志 `wall-clock deadline exceeded (90.0s)`）。本轮同一路径 0 次超时，因为
POST 都在 90s 内返回——但余量很薄：

| 用例 | 编辑器单次调用 | attempts | 输出 tokens |
| --- | ---: | ---: | ---: |
| 腾讯 #1 | 81.9s | 1 | 2923 |
| Reolink #1 | 105.2s | 2 | 3362 |
| Reolink #3 | 131.3s | 2 | 4775 |
| Dida #2 | 152.7s | 2 | 4327 |

>90s 的那几条都是**两个 POST 之和**（首发 schema/parse 失败后带反馈重试），
所以没触发 deadline。但 81.9s 的单发已逼近 90s 线。结论：**墙钟值得放宽**
（例如 `RESUALIGN_ROLE_TIMEOUT_EDITOR` 90 → 150），最坏 2×150=300s 仍远低于
watchdog 1800s。但它是 AIE 决策域的护栏数字（`tests/api/test_r4_aie_guardrails.py`
与 `test_settings_routes.py` 锁着），要改得先拍，不顺手调。
