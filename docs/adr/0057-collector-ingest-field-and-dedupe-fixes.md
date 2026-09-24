# ADR-0057: 采集器摄入三修——URL 去重保留岗位标识、薪资文本落库、预分析失败可读

- **状态**: 已采纳
- **日期**: 2026-09-24
- **依据**: ADR-0042 决定 6e（逐项例外）；用户主动派单（「同一官网两个不同的
  岗位会覆盖掉，现在一键预分析功能也失效了」「抓取到的信息虽然完整但是不能
  正确填入到岗位信息框里」）
- **关系**: 只解冻本 ADR 列出的三处摄入/预分析路径；不动探针判据、自用线
  阈值与冻结令其余部分

## 背景：三个各自独立、但都落在同一条采集→入库链上的缺陷

### 1. 同一官网的多个岗位被折叠成一行

`job_library._normalize_source_url` 用 `re.sub(r"[?#].*$", "", value)` 把
查询串与 fragment 整段删掉。而多数招聘官网的**岗位身份就在查询串或
fragment 里**：腾讯 `?postId=`、北森 `?jobAdId=`、Moka `#/job/<uuid>`、
阿里 `?deptCodes=`。结果同一域名下的所有岗位共享一个 dedupe key，第二次
摄入被判为 `duplicate`，用户看到的现象就是「覆盖掉」。

实测（修复前，活服务）：向 `/api/jobs/local-ingest` 投递
`join.qq.com/post_detail.html?postid=A` 与 `?postid=B` 两个不同岗位，
两次都返回 `duplicate`，且都指向同一条已存在的腾讯行。

### 2. 采集器抓到的薪资文本没有落进岗位信息

采集器把薪资行作为 `salary_text`（如 `20-30K·15薪`）上报，
`LocalIngestRequest.salary_text` 也一路传到了 `_local_ingest_job`，但
`_deterministic_job_fields` 只读 `salary_min`/`salary_max`，从不解析
`salary_text`。于是页面上明明有薪资，岗位编辑框里的「最低/最高薪资」却是
空的。2026-08-27 的「去膨胀」决定（不再从 **JD 正文**里挖薪资）被过度
执行成了「连显式上报的薪资字段也丢掉」。

### 3. 预分析遇到欠费只报 500，批量还会逐行重试

供应商返回 HTTP 402（余额不足）时，`LLMResponseError.code == "quota"`。
该异常在 `preanalyze_job` 里从 profile 分支逃逸：

- 单岗位路由 `POST /api/jobs/{id}/preanalyze` 变成 500 `internal_error`，
  用户看不到任何可执行原因；
- 批量 `_run_preanalyze_batch` 只把每行记进 `errors` 继续跑，**不会**命中
  它自己已有的 `PreanalyzeUnavailable` 分支，于是 18 行 × 2 次尝试全部
  打水漂。

根因是账号欠费（外部状态），不是代码回归；代码的问题是**没有把定义性
失败讲清楚**。

## 决定

**决定 1（URL 去重保留身份，只删噪声）**：`_normalize_source_url` 改为
保留查询串与 fragment，仅剔除已知的追踪/语言噪声键（`utm_*`、`locale`、
`from`、`src`、`ref`、`spm`、`share*`、`activityGuid`、`ActivityJumpPage`
等），查询参数排序后重建，整体小写。`#/job/<uuid>` 这类 SPA 路由原样保留。
身份参数绝不丢。

**决定 2（存量行惰性重算 key）**：新增 `JobLibraryStore._reconcile_url_dedupe_keys`，
在 `_apply_migrations` 之后对 `source_type='url'` 的行按各自 `source_url`
重算 dedupe key；键已正确或新键与既有行冲突（`IntegrityError`）的行跳过。
幂等、廉价，随 store 首次初始化执行——**不**新增版本化迁移（迁移器只支持
SQL 脚本，URL 归一化无法用 SQL 表达）。修复前已被合并掉的数据无法在此恢复，
属于已知不可逆损失。

**决定 3（显式上报的薪资文本要落库）**：`_deterministic_job_fields` 在
`salary_min`/`salary_max` 都缺省时解析 `salary_text`。解析器
（`job_library._parse_salary_text`，`job_table._parse_salary` 改为复用它）
**要求存在量级单位**（K/千/万）：`20-30K`→20000/30000、`1.2万-2万`→
12000/20000；`面议`、`200-300元/天`、`8000-12000` 一律返回 `(None, None)`
——日薪、经验区间、人数都不是月薪，宁缺勿错。**JD 正文仍不挖薪资**，去膨胀
决定只在这一处被收窄。

**决定 4（预分析失败必须可读，且批量早停）**：

- `preanalyze_job` 在第一次 LLM 调用前先跑 `_probe_active_llm_quick`
  （与工作台 A1 同源），定义性阻断直接抛
  `PreanalyzeUnavailable(status_code=503, detail=<可执行原因>)`；
- LLM 调用段整体包一层 `except LLMResponseError`，按 `exc.code ∈ {auth, quota}`
  映射为同一个 `PreanalyzeUnavailable`（分支稳定契约，不解析消息文本）；
- 批量因此命中既有 `PreanalyzeUnavailable` 分支，`stopped=True` 并在首行
  停止，不再逐行重试；
- 前端「一键预分析」在 `stopped && errors` 时直接 toast 后端给出的原因，
  而不是只报「失败 1」。

**决定 5（不做）**：不新增 HTTP 路由、不改请求/响应 schema、不改数据库列、
不动 `contracts/openapi-current.json`、不改探针判据与自用线阈值。

## 后果

- 同一官网的多个岗位各自成行；同一岗位带不同追踪参数仍然只入一行。
- 存量 URL 行在首次初始化时被重算为保留身份的 key；已合并的行保持合并。
- 采集器抓到的薪资区间出现在岗位编辑框里；无法判定为月薪的文本保持空值。
- 欠费/鉴权失败时用户看到「余额不足：请给该节点充值，或到「系统设置 →
  模型节点」切换可用节点后重试」，且批量立即停止，不再空烧额度。

## 验证

- `tests/test_job_library.py`：URL 归一化 3 例、薪资解析 1 例、同域两岗位
  各自创建、存量 key 重算。
- `tests/test_local_ingest_snapshots.py`：同域两岗位 + 追踪参数去重、
  薪资文本落库、无法解析的薪资保持空值。
- `tests/test_job_api.py`：402/欠费映射为 503 且批量 `stopped=True`。
- 活服务实测：两个 `?postid=` 岗位各自 `created`，薪资
  `20000/30000`；`POST /api/jobs/{id}/preanalyze` → 503 +
  「余额不足…」。

## 与既有 ADR 的关系

- **ADR-0042 决定 6e**：本 ADR 即该条的逐项例外记录（用户主动派单、修复
  数据丢失与不可读失败），冻结令其余部分继续有效。
- **ADR-0055**：岗位表自动同步与本 ADR 共用 `_dedupe_key_for`，本 ADR 的
  归一化改动同样作用于该路径；两者不互相授权。
- **ADR-0056**：同一批用户派单里的设置页护栏清理，与本 ADR 无重叠。
