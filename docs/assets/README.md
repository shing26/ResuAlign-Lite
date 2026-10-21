# README 视觉资产

`scripts/make_readme_figures.py` 确定性生成这里的两张 SVG。同样的输入产出同样的
字节，**图里不含时间戳**，重跑不会造成无意义 diff。

| 文件 | 用在哪 | 画的是 |
| --- | --- | --- |
| [`gate-before-after.svg`](gate-before-after.svg) | README「效果对照」 | 原始简历 → 本地规则打标缺口 → 反幻觉门禁重写 |
| [`hallucination-rate.svg`](hallucination-rate.svg) | README「效果对照」 | 8 条编造断言在门禁前后的到达率 + 判分装置 |

## 重新生成

```powershell
python scripts\make_readme_figures.py            # 写盘
python scripts\make_readme_figures.py --check    # 只校验，有漂移退出码 1
```

图里的数字不是手敲的常量，全部来自下面两条命令与三份文件：

```powershell
$env:PYTHONPATH='src'
python benchmarks\run_benchmark.py --offline     # 对抗用例：0 条编造断言进入输出
python -m benchmarks.agent.harness.probes        # 6 项探针 9 组全绿
```

- `benchmarks/cases/adversarial_hallucination_claims.json` / `..._projects.json`
  —— 两例合成对抗用例，`must_not_contain` 各 4 条，合计 n=8。
- `tests/fixtures/gate/expected.en.json` —— 门禁黄金 fixtures：9 条 diff → usable 5 · blocked 4。
- `benchmarks/agent/` —— 机械判卷 harness 与 PHASE0_PROTOCOL。

## 面板 2 的取数片段

「本地规则打标缺口」那一栏是以下两个函数的**真实输出**（输入＝对抗用例原文，
`must_have_skills` 抄自该用例的 JD 文本）：

```python
import json
from resualign.rule_diagnose import diagnose_resume_local
from resualign.match_scorer import keyword_coverage_score

case = json.load(open("benchmarks/cases/adversarial_hallucination_claims.json", encoding="utf-8"))
resume = case["resume_text"]

diagnose_resume_local(resume)
# {'score': 50, 'skills': [PostgreSQL, FastAPI, Python, Docker, Flask, Redis, REST],
#  'issues': ['未检测到手机号', '未检测到邮箱', '量化成果不足'], 'fallback_used': True}

keyword_coverage_score(
    {"must_have_skills": ["Python", "FastAPI", "async endpoints", "Redis caching",
                          "Docker", "Kubernetes", "low latency"]},
    resume,
)
# {'required': 7, 'matched': 3, 'ratio': 0.429,
#  'missing': ['async endpoints', 'Redis caching', 'Kubernetes', 'low latency']}
```

面板 3 的「拦截」判定同样是跑出来的，不是画上去的：

```python
from resualign import gate
# item = 锚点逐字真实、载荷编造的那条 modify（见 benchmarks/run_benchmark.py 的
#         FakeLLMClient._fabricated_diff）
gate.verdict(item, resume)
# {'verdict': 'blocked', 'reason': 'fabricated',
#  'detail': 'number 20; term Stanford; term AWS; term Glue; term TensorFlow; …'}
```

## 口径与边界（改图前先读）

- **n=8 是构造注入，不是统计抽样**。所以图上只报计数与到达率，不做任何统计推断；
  这正是 README 里「样本不足只报计数，不给误导性比率」的同一条口径。
- **LLM-as-a-Judge 那一栏刻意不出数**。`evaluator/v3` 是真裁判（输出
  `hallucination_detected` / `hallucination_details`），但它需要真实模型节点，
  且 2 例样本支持不了比率。Phase 0 的判分改用机械判卷，协议原话：
  「裁判必须比考生便宜且不会做梦」。
- **无门禁基线（8/8）是构造事实**：对抗载荷写在 `FakeLLMClient` 的提案里；
  门禁后 0/8 才是实测（`must_not_contain` 命中即 `AssertionError`）。
- 不要在 SVG 里直接改字或加数——`--check` 会让生成器与产物对不上。

## 出图前自检

SVG 是给 GitHub 渲染的：只用了 presentation attributes，没有 `<style>`、脚本或
外链字体（唯一的外部字符串是必需的 `xmlns` 命名空间），避免被 markdown 图片
代理清洗掉。改完用仓库已装的 Playwright 过一眼：

```powershell
python -c "import pathlib; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); pg=b.new_page(device_scale_factor=2); pg.goto(pathlib.Path('docs/assets/gate-before-after.svg').resolve().as_uri()); pg.query_selector('svg').screenshot(path='.scratch/gate-before-after.png'); b.close(); p.stop()"
```

重点看三件事：面板之间的文字有没有越界、条形的数值标签有没有和轨道重叠、
中英文混排有没有被截断。
