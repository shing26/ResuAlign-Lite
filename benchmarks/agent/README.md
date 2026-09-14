# Phase 0 判卷 Harness（`benchmarks/agent/`）

裁决「循环协议该用 tools 还是 template」所需的**离线判卷装置**。对应协议：
[`PHASE0_PROTOCOL.md`](PHASE0_PROTOCOL.md)；题面与判分期望：
[`fixtures/phase0_q4_v1.jsonl`](fixtures/phase0_q4_v1.jsonl)（52 行封卷件）。

边界（与 `benchmarks/README.md` 那条产品管线 benchmark 无关，两套装置互不引用）：

- 只依赖标准库，**不 import 任何产品模块**（`llm/tailor/engine/models/routers` 一概不碰），
  因此它评的是「协议能不能被模型满足」，不是「产品能不能跑」。
- 判分全部由 fixture 字段驱动：凡协议/题面写成散文而此处无法机械执行的断言，一律进
  `unjudged` 清单或 `harness_gap`，**禁止静默放行**。`harness_gap` 非空 = 该 run 无效。
- 探针（`probes`）完全离线，零网络、零密钥。只有 `runner` 显式跑 cell 时才发请求。

## 文件

| 文件 | 作用 |
| --- | --- |
| `harness/core.py` | Fixture 加载（append-only：同 id 后行覆写前行）、`visible_text()` 按 prompt_contract 装配题面、JSON-Schema + DSL 校验、选择器命中判定、`Sim`（观察投递 + 出处池 + 审批档位）、blob hash |
| `harness/judge.py` | §4.1–4.5 与 v1.1 §6 附录的机械判分器，返回 `{passed,reasons,repairs,calls,steps,unjudged,harness_gap,fixture_version}` |
| `harness/arms.py` | `ScriptedArm`（复演脚本，供探针）/ `TemplateArm`+`ToolsArm` 合体的 `HttpArm`（urllib，两臂同归一化为同一 attempt 记录）；响应语义集中在 `decide_action()` |
| `harness/actor.py` | 完美模型演员（动作流与参考答文**从 fixture 自身的期望集/剧本推导**）+ 9 个违规注入器 |
| `harness/probes.py` | P1–P6 自检（见下） |
| `harness/runner.py` | 8 格实测驱动：attempt 分母聚合、协议 §1 等效线判定、封卷 hash 绑定、结果落 `results/` |
| `harness/overlay_from_pack.py` | 从输入包 md 抽覆写行 → 写到**被 git 忽略**的 `.scratch/phase0/v11_overlay.jsonl`（绝不写 fixture）。v1.1 已封卷入库，此工具转为未来版本起草备用 |
| `cells.example.json` | 8 格配置（节点 × thinking 变体 × 协议臂）；只写密钥**变量名** |

## 跑探针（改判分器后必跑，离线）

```bash
cd D:/ResuAlign-Lite
python -m benchmarks.agent.harness.probes --verbose
```

六探针各自钉住一件「不验就会静默出错」的事：

1. **P1 完美模型** — 30 行 × 两条代码路径（arm / direct）在 v1 与 v1.1 两套生效文本上全过，
   且 `harness_gap` 全空。演员跟着 fixture 走却过不了判分器 = fixture 或判分器有病。
2. **P2 注入必挂** — 9 个违规（发明 id / 无出处数字 / 审批幻觉 / 多余调用 / 提前宣告完成 /
   超帽 / 假完成 / 先提议后告警 / 状态谎报）必须被抓住，且**抓到的是预期那条 reason 码**。
3. **P3 身份洞** — 用 `job_4×2` 替 `job_7`、两个无 key 调用报 `done==2`、夹一笔多余写：
   v1 必须「过」（这就是 v1 的洞），v1.1 必须「挂」（洞已堵）。方向反了或两边同判都算失败。
4. **P4 repair 记账** — ≤2 次无效输出可重试并通过，第 3 次判 `repair_over_cap`。
5. **P6 臂语义** — 一条响应到底算不算「派发调用」：有剧本的行（MD/BS/SB）拿到
   `tool_calls` 一律派发（吞掉会造成静默死循环，把 harness 缺陷伪装成模型失败）；
   填空题（SS 行，fixture 里没有观察剧本）拿到 `tool_calls` 记一次 repair（计入
   steps、**不写入 actions**），**不派发**——否则等于让 harness 凭空造观察。散文/空内容不算答案。
6. **P5 判分边界** — SS-05 弱判在 v1 过、收紧后在 v1.1 挂；题面作者括注（`（world…）`）
   v1 命中 6 处、v1.1 命中 0 处。

基线来源（v1.1 封卷后确立）：**v1 = 封卷 git 对象** `git show f25a22f:…jsonl`
（blob `f097c88c…` 钉死在探针里，基线被偷换会先于判分开火）；**v1.1 = 工作树
生效视图**（`c92bf37` 纯追加 15 行同 id 覆写，last-wins）。append-only 封卷之后
工作树里不存在纯 v1 文本，P3/P5 只能对 git 对象重放——「v1 会放过这三个替身」
正是 §6 立洞的证据。

当前状态：**6 项 9 组全绿**（封卷 v1 重放 + 工作树 v1.1）。

## 跑 8 格实测

```bash
# 0) 先看计划与封卷 hash，不发任何请求
python -m benchmarks.agent.harness.runner --dry-run

# 1) 单格烟测（本地 ollama，无需密钥）；--verbose 逐行打印判定与耗时
python -m benchmarks.agent.harness.runner --cell-id n2-t-off-template --attempts 1 --only MD-01 --verbose

# 2) 正式：8 格 × 30 行 × 3 attempt ≈ 720 次请求（v1.1 复测再一倍）
export RESUALIGN_N1_API_KEY=...          # 只进环境，不进文件
python -m benchmarks.agent.harness.runner --cell-id n1-t-on-tools ... --sleep 0.3
```

`cells.example.json` 里 N1 的 `base_url` 是占位符（须从产品节点配置抄实际值），
N2 的 thinking-on 两格标 `status=n_a` 并写明理由——协议 §0 要求「不静默缩表」，
所以行留着，runner 跳过并在结果 JSON 里记 `skipped`。预算与超时按 §5：
`temperature=0`、单调用 90s（网关）/120s（本地）、attempt 内 repair ≤2。

`temperature_used` 只有节点回显时才有值，否则逐行记 `null`、聚合记
`temperature_unverified`（协议 §5 不许高温偷走「3 次重复吸收方差」的口径）——
非零或未确认的 run 不算达标证据。ollama `/v1` 实测**不回显** `temperature`
（本地两格因此必然 temp_unverified=全部），这是节点能力，不是 harness 缺陷。

tools 臂的 SS 填空题下发 `tool_choice="none"`，但**节点可以不理**（ollama
qwen2.5:7b 实测照旧发起 `tool_calls`）。harness 的处理写死在 `decide_action()`：
SS 行在封卷 fixture 里**没有观察剧本**，因此该调用无从派发（派发＝harness 凭空造
观察），记一次 repair：调用次数计入 `steps`（SS 判分口径），但**不写入 actions**
（judge 的 SS 规则要求恰好一次），只回填会话历史并附一句「直接输出目标 JSON 对象」
提示；单 attempt 的输出数帽 3（= 1 + 2 repair），不许用 14 次请求去磨一道填空题。
MD/BS/SB 行拿到 `tool_calls` 一律派发——
吞掉调用会造成静默死循环，把 harness 缺陷伪装成模型失败（P6 钉住这两种读法）。

结果 JSON 落 `results/phase0-<版本>-<时间戳>.json`，含：`sealed`（fixture/协议 blob hash +
生效题面 hash）、逐 attempt 的 actions/reasons/repairs/耗时、聚合体的 `checks`
（协议 §1 等效线：tools SS≥35/36、MD≥24/30；template SS=36/36、MD≥27/30；BS+SB=24/24）
与 `unjudged` / `harness_gap` / `integrity_hits`。**attempt 数不足 90 的 run 一律标
`incomplete`，不得用来宣称过线。**

## 已知机械代理与未判项（照抄，别当已判）

| 项 | 现状 | 影响 |
| --- | --- | --- |
| `must_cite_dims` | 中文词表代理（`DIM_GLOSS`） | 维度英文名写对但中文没提 → 判挂；反之亦然 |
| `output_schema` | 只做类型/形状校验，DSL 之外的 enum/正则不判 | SS 行「类型对但值荒谬」靠 `expected`/谓词兜 |
| `report_assertions` | 逐条白名单代理（todos 非空、不谎报、继续选项、未执行审批…） | todos **内容覆盖率不判**，只判非空 |
| `must_before_propose` | 按消息顺序判：告警词表取自该行非数字 `required_regex` | 若某行没有非数字 required_regex，则记 `unjudged` 不硬判 |
| `done/pending 名单一致性` | 仅 v1.1 生效（`judgment_contract.done_list_consistency`） | v1 上这类谎报不被判——正是 v1 的已知洞 |
| 剧本 key 简写 | `job_n8+n9+n10` 由**演员侧**补全前缀；判分仍按 token 子串命中 | 判分器不因此放宽任何身份要求 |
| 数字出处豁免 | 仅 4 位年份、或恰为锚点月/日的 1–2 位数 | v1.1 勘误取消「小数字免检」后，`42` 这类编造必挂（P2 已钉） |

## 两处需要协议侧回应的发现（写在这里，不改判分器口径）

1. **template 臂无法表达「调用前的话」**：该臂一步只有一个 JSON 对象，`must_before_propose`
   的「消息顺序判」只剩一种可实现读法——*不执行审批档调用*，把提议写进结论文本。
   v1.1 把 `save_final_draft` 写成 `max1`（允许 0 次）正好与此一致；若哪天改成必填该 key，
   两臂对 MD-08 就不等价了。
2. **v1.1 的默认期望集**（行内缺 `expected_multiset` ⇒ 每个 script key 恰一次）与
   `approval_trap` 行天然冲突：一次 attempt 里不可能含「人已确认」这一事件。故默认集
   **不含审批档 key**，只由 `accept_forms`/`conclusion_rules` 判审批语义（已在
   `judge_multiset` 的 defaulted 分支实现，并进 `unjudged`）。
