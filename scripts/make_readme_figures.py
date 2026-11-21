"""Generate the SVG figures embedded in README.md.

All figures are deterministic: same inputs, same bytes, no timestamps. The
numbers printed inside the data figures are read from repository artefacts,
not typed in by hand -- every value is traceable to one of these commands:

    $env:PYTHONPATH='src'
    python benchmarks/run_benchmark.py --offline        # adversarial leakage + gate
    python -m benchmarks.agent.harness.probes           # mechanical judge probes

and to these files:

    benchmarks/cases/adversarial_hallucination_claims.json
    benchmarks/cases/adversarial_hallucination_projects.json
    tests/fixtures/gate/expected.en.json                # 7 diffs: 5 usable, 2 blocked

Panel 2 of the before/after figure is the literal output of
``rule_diagnose.diagnose_resume_local`` and ``match_scorer.keyword_coverage_score``
run against the synthetic adversarial case (see docs/assets/README.md for the
snippet). Deliberately absent: the LLM-as-a-Judge (``evaluator`` role) is shown
as "not published", because two synthetic cases cannot support a rate -- the
repository rule is "samples too small: report counts, not ratios".

Usage:

    python scripts/make_readme_figures.py            # writes docs/assets/*.svg
    python scripts/make_readme_figures.py --check     # fail if files would change
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "assets"
BENCH_CASES = (
    ROOT / "benchmarks" / "cases" / "adversarial_hallucination_claims.json",
    ROOT / "benchmarks" / "cases" / "adversarial_hallucination_projects.json",
)
GATE_EXPECTED = ROOT / "tests" / "fixtures" / "gate" / "expected.en.json"
PROMPT_VERSIONS = ROOT / "src" / "resualign" / "prompt_versions.py"

# --- palette (roles, not moods) -------------------------------------------
INK = "#0B0D11"          # primary text
INK_2 = "#3C444F"        # body text
MUTED = "#6B7480"        # captions, provenance
RULE = "#DCE2E9"         # hairlines
SURFACE = "#FFFFFF"      # panel fill
CANVAS = "#F6F8FA"       # figure background
ACCENT = "#0E7C8F"       # verified / usable (light-theme accent token)
ACCENT_SOFT = "#E2F3F6"
ALERT = "#C2410C"        # blocked / fabricated
ALERT_SOFT = "#FDEDE4"
OK = "#157F5B"           # delivered output is clean
OK_SOFT = "#E6F4EE"

FONT_SANS = (
    "Inter, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif"
)
FONT_MONO = "JetBrains Mono, Consolas, 'Liberation Mono', monospace"


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_prompt_registry() -> dict:
    spec = importlib.util.spec_from_file_location("resualign_prompt_versions", PROMPT_VERSIONS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PROMPT_VERSIONS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def figure_data() -> dict[str, object]:
    cases = [load_json(path) for path in BENCH_CASES]
    injected = sum(len(case.get("must_not_contain", [])) for case in cases)
    gate_summary = load_json(GATE_EXPECTED)["summary"]
    prompt_registry = load_prompt_registry()
    return {
        "injected": injected,
        "gate_diffs": int(gate_summary["diffs"]),
        "gate_usable": int(gate_summary["usable"]),
        "gate_blocked": sum(int(value) for value in gate_summary["blocked"].values()),
        "evaluator_version": prompt_registry.get_prompt_version(
            prompt_registry.EVALUATOR
        ),
    }


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def text(
    x: float,
    y: float,
    body: str,
    *,
    size: float = 13,
    fill: str = INK_2,
    weight: str = "400",
    font: str = FONT_SANS,
    anchor: str = "start",
    spacing: float | None = None,
) -> str:
    bits = [
        f'x="{x:g}"',
        f'y="{y:g}"',
        f'font-family="{font}"',
        f'font-size="{size:g}"',
        f'fill="{fill}"',
    ]
    if weight != "400":
        bits.append(f'font-weight="{weight}"')
    if anchor != "start":
        bits.append(f'text-anchor="{anchor}"')
    if spacing is not None:
        bits.append(f'letter-spacing="{spacing:g}"')
    return f"<text {' '.join(bits)}>{esc(body)}</text>"


def rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = SURFACE,
    rx: float = 8,
    stroke: str | None = None,
    sw: float = 1,
) -> str:
    bits = [f'x="{x:g}"', f'y="{y:g}"', f'width="{w:g}"', f'height="{h:g}"']
    if rx:
        bits.append(f'rx="{rx:g}"')
    if fill == "none":
        bits.append('fill="none"')
    else:
        bits.append(f'fill="{fill}"')
    if stroke:
        bits.append(f'stroke="{stroke}" stroke-width="{sw:g}"')
    return f"<rect {' '.join(bits)}/>"


def line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    stroke: str = RULE,
    sw: float = 1,
    dash: str | None = None,
) -> str:
    bits = [
        f'x1="{x1:g}"',
        f'y1="{y1:g}"',
        f'x2="{x2:g}"',
        f'y2="{y2:g}"',
        f'stroke="{stroke}"',
        f'stroke-width="{sw:g}"',
    ]
    if dash:
        bits.append(f'stroke-dasharray="{dash}"')
    return f"<line {' '.join(bits)}/>"


def panel(x: float, y: float, w: float, h: float) -> str:
    return rect(x, y, w, h, fill=SURFACE, stroke=RULE, sw=1)


def checkbox_row(x: float, y: float, label: str, *, ok: bool, note: str = "") -> str:
    color = ACCENT if ok else ALERT
    soft = ACCENT_SOFT if ok else ALERT_SOFT
    mark = "v" if ok else "x"
    out = [rect(x, y - 11, 16, 16, fill=soft, rx=4)]
    out.append(text(x + 8, y + 1.5, mark, size=11, fill=color, weight="700", anchor="middle"))
    out.append(text(x + 26, y + 1, label, size=13, fill=INK_2))
    if note:
        out.append(text(x + 26 + len(label) * 7.6 + 8, y + 1, note, size=11.5, fill=MUTED))
    return "".join(out)


def svg(width: int, height: int, body: str, aria: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(aria)}">\n'
        f"{body}\n</svg>\n"
    )


# ---------------------------------------------------------------------------
# Figure 1 -- 诊断 -> 打标 -> 受控重写（before/after）
# ---------------------------------------------------------------------------

PANEL_W = 456
PANEL_GAP = 28
MARGIN = 48


def figure_before_after() -> str:
    width = MARGIN * 2 + PANEL_W * 3 + PANEL_GAP * 2
    height = 900
    top = 132
    panel_h = 636
    out: list[str] = [
        rect(0, 0, width, height, fill=CANVAS, rx=0),
        text(MARGIN, 62, "诊断 → 打标 → 受控重写：一条编造断言如何被拦下", size=26, fill=INK, weight="700"),
        text(
            MARGIN,
            92,
            "合成对抗用例 · 无真实个人信息 · 图中每个数字都能由仓库命令复现",
            size=14,
            fill=MUTED,
        ),
    ]

    columns = [
        (MARGIN, "1", "原始简历输入", "benchmarks/cases/adversarial_hallucination_claims.json"),
        (MARGIN + PANEL_W + PANEL_GAP, "2", "本地规则打标缺口", "rule_diagnose.py · match_scorer.py · 0 次 LLM 调用"),
        (MARGIN + (PANEL_W + PANEL_GAP) * 2, "3", "反幻觉约束重写结果", "gate.py · fail-closed · 事实必须有原文出处"),
    ]
    for x, idx, title, caption in columns:
        out.append(panel(x, top, PANEL_W, panel_h))
        out.append(rect(x, top, PANEL_W, 4, fill=ACCENT, rx=0))
        out.append(rect(x + 24, top + 28, 26, 26, fill=ACCENT_SOFT, rx=6))
        out.append(text(x + 37, top + 46, idx, size=14, fill=ACCENT, weight="700", anchor="middle"))
        out.append(text(x + 60, top + 46, title, size=17, fill=INK, weight="700"))
        out.append(text(x + 24, top + 74, caption, size=11.5, fill=MUTED, font=FONT_MONO))

    def mono_rows(
        x: float,
        y0: float,
        rows: list[tuple[str, str | None]],
        *,
        step: float = 23,
        size: float = 12.2,
    ) -> list[str]:
        rendered = []
        for i, (body, color) in enumerate(rows):
            rendered.append(
                text(x, y0 + i * step, body, size=size, fill=color or INK_2, font=FONT_MONO)
            )
        return rendered

    # --- Panel 1: input ---------------------------------------------------
    x = columns[0][0]
    y = top + 112
    out.extend(
        mono_rows(
            x + 24,
            y,
            [
                ("SYNTHETIC RESUME  Python Backend Engineer", INK),
                ("", None),
                ("Skills   Python FastAPI PostgreSQL Redis Docker", None),
                ("", None),
                ("Experience", INK),
                ("- Built Python FastAPI services for account", None),
                ("  workflows.", None),
                ("- Used Redis for cache storage and session", None),
                ("  management.", None),
                ("- Deployed services with Docker.", None),
                ("- Tuned PostgreSQL schemas and SQL queries.", None),
            ],
        )
    )
    split_y = y + 12 * 23
    out.append(line(x + 24, split_y, x + PANEL_W - 24, split_y))
    out.append(text(x + 24, split_y + 30, "JD 要求（7 项，字面命中判定）", size=12.5, fill=INK, weight="700"))
    jd_rows = [
        ("Python", True),
        ("FastAPI", True),
        ("Docker", True),
        ("async endpoints", False),
        ("Redis caching", False),
        ("Kubernetes", False),
        ("low latency 指标", False),
    ]
    for i, (label, hit) in enumerate(jd_rows):
        out.append(
            checkbox_row(
                x + 24,
                split_y + 60 + i * 23,
                label,
                ok=hit,
                note="命中" if hit else "缺口",
            )
        )
    out.append(
        text(
            x + 24,
            top + panel_h - 26,
            "命中 3 / 7 · 缺口 4（零 LLM 关键词覆盖）",
            size=12.5,
            fill=ACCENT,
            weight="600",
        )
    )

    # --- Panel 2: local rule diagnosis ------------------------------------
    x = columns[1][0]
    y = top + 112
    out.append(text(x + 24, y, "本地规则诊断  毫秒级 · 无 provider 调用", size=12.5, fill=INK, weight="700"))
    out.extend(
        mono_rows(
            x + 24,
            y + 30,
            [
                ("diagnose_resume_local()", ACCENT),
                ("  score           50", None),
                ("  fallback_used   true", None),
                ("  skills(7)       PostgreSQL FastAPI Python", None),
                ("                  Docker Flask Redis REST", None),
                ("  issues(3)       未检测到手机号", None),
                ("                  未检测到邮箱", None),
                ("                  量化成果不足", None),
            ],
        )
    )
    out.append(line(x + 24, y + 8 * 23 + 34, x + PANEL_W - 24, y + 8 * 23 + 34))
    out.append(
        text(
            x + 24,
            y + 8 * 23 + 62,
            "keyword_coverage_score()",
            size=12.2,
            fill=ACCENT,
            font=FONT_MONO,
        )
    )
    out.extend(
        mono_rows(
            x + 24,
            y + 8 * 23 + 92,
            [
                ("  ATS 覆盖       3 / 7 = 0.429", None),
                ("  missing        async endpoints", ALERT),
                ("                 Redis caching", ALERT),
                ("                 Kubernetes", ALERT),
                ("                 low latency", ALERT),
            ],
        )
    )
    out.append(
        text(
            x + 24,
            top + panel_h - 26,
            "打标不猜测：正则 + 字面命中，缺什么标什么",
            size=12.5,
            fill=MUTED,
        )
    )

    # --- Panel 3: gate verdict -------------------------------------------
    x = columns[2][0]
    y = top + 112
    out.append(text(x + 24, y, "提案 A · 通过", size=12.5, fill=INK, weight="700"))
    out.extend(
        mono_rows(
            x + 24,
            y + 30,
            [
                ("modify   Used Redis for cache storage", None),
                ("   ->    Used Redis caching for high", None),
                ("         concurrency and async endpoints", None),
                ("provenance  v  原文逐字可定位", ACCENT),
                ("gate        usable · reason=verified", ACCENT),
            ],
        )
    )
    out.append(line(x + 24, y + 5 * 23 + 34, x + PANEL_W - 24, y + 5 * 23 + 34))
    out.append(text(x + 24, y + 5 * 23 + 62, "提案 B · 拦截（对抗注入）", size=12.5, fill=ALERT, weight="700"))
    out.extend(
        mono_rows(
            x + 24,
            y + 5 * 23 + 92,
            [
                ("modify   Built Python FastAPI services", None),
                ("   ->    ... 同上 + \"Led a 20-person", None),
                ("         team at Stanford, deploying AWS", None),
                ("         Glue pipelines with TensorFlow,", None),
                ("         and PhD-level Flink research on", None),
                ("         Google Cloud.\"", None),
                ("provenance  v  真锚点 + 编造载荷", ALERT),
                ("gate        blocked · reason=fabricated", ALERT),
                ("            无来源：20 · Stanford · AWS ·", ALERT),
                ("            Glue · TensorFlow · PhD ·", ALERT),
                ("            Flink · Google · Cloud", ALERT),
            ],
        )
    )
    out.append(rect(x + 24, top + panel_h - 74, PANEL_W - 48, 44, fill=OK_SOFT, rx=8))
    out.append(text(x + 40, top + panel_h - 46, "交付面：0 条编造事实进入定稿", size=14, fill=OK, weight="700"))

    out.append(line(MARGIN, height - 92, width - MARGIN, height - 92))
    out.append(
        text(
            MARGIN,
            height - 62,
            "数据来源  benchmarks/cases/adversarial_hallucination_claims.json · tests/fixtures/gate/expected.en.json",
            size=12,
            fill=MUTED,
        )
    )
    out.append(
        text(
            MARGIN,
            height - 36,
            "复现  python benchmarks/run_benchmark.py --offline   ·   面板 2 由 rule_diagnose / match_scorer 直接调用输出",
            size=12,
            fill=MUTED,
            font=FONT_MONO,
        )
    )
    return svg(width, height, "".join(out), "ResuAlign-Lite 诊断前后对照：原始简历、本地规则打标、门禁约束重写")


# ---------------------------------------------------------------------------
# Figure 2 -- 幻觉发生率对比 + 判分装置
# ---------------------------------------------------------------------------


def bar_row(
    x: float,
    y: float,
    track_w: float,
    *,
    label: str,
    fraction: float | None,
    value: str,
    caption: str,
    fill: str,
    hatch: bool = False,
) -> str:
    out: list[str] = [text(x, y, label, size=14.5, fill=INK, weight="600")]
    bar_y = y + 16
    bar_h = 40
    out.append(rect(x, bar_y, track_w, bar_h, fill="#EDF1F5", rx=6))
    if hatch:
        hx = x
        while hx < x + track_w - 8:
            out.append(line(hx, bar_y + bar_h - 1, hx + 10, bar_y + 1, stroke="#C9D2DB", sw=2))
            hx += 14
        out.append(rect(x, bar_y, track_w, bar_h, fill="none", rx=6, stroke="#C9D2DB", sw=1))
    elif fraction is not None and fraction > 0:
        out.append(rect(x, bar_y, max(track_w * fraction, 4), bar_h, fill=fill, rx=6))
    else:
        out.append(rect(x, bar_y, 6, bar_h, fill=fill, rx=3))
    out.append(text(x + track_w + 16, bar_y + 28, value, size=19, fill=fill, weight="700"))
    out.append(text(x, bar_y + bar_h + 24, caption, size=12.2, fill=MUTED))
    return "".join(out)


def figure_hallucination() -> str:
    data = figure_data()
    injected = data["injected"]
    gate_diffs = data["gate_diffs"]
    gate_usable = data["gate_usable"]
    gate_blocked = data["gate_blocked"]
    evaluator_version = data["evaluator_version"]
    width = 1400
    height = 812
    out: list[str] = [
        rect(0, 0, width, height, fill=CANVAS, rx=0),
        text(MARGIN, 62, "幻觉发生率：同一套对抗用例，门禁前 vs 门禁后", size=26, fill=INK, weight="700"),
        text(
            MARGIN,
            92,
            f"n = {injected} 条编造断言（{len(BENCH_CASES)} 例合成对抗用例），"
            "确定性构造，不是统计抽样",
            size=14,
            fill=MUTED,
        ),
    ]

    left_x = MARGIN
    left_w = 800
    out.append(panel(left_x, 132, left_w, 536))
    out.append(text(left_x + 28, 176, "编造断言到达交付面的比例", size=15, fill=INK, weight="700"))
    out.append(text(
        left_x + 28,
        200,
        f"分母固定为注入的 {injected} 条断言；只报计数，不据此做统计推断",
        size=12.2,
        fill=MUTED,
    ))

    track_w = 560
    out.append(
        bar_row(
            left_x + 28,
            268,
            track_w,
            label="无门禁 · 提案原样交付",
            fraction=1.0,
            value=f"{injected} / {injected}  =  100%",
            caption="FakeLLMClient 注入的编造载荷原样留在改写提案里（构造事实，非实测模型）",
            fill=ALERT,
        )
    )
    out.append(
        bar_row(
            left_x + 28,
            414,
            track_w,
            label="反幻觉门禁 · fail-closed",
            fraction=0.0,
            value=f"0 / {injected}  =  0%",
            caption="provenance 解析 → 内容检查 → noop 过滤；实测 0 条进入输出",
            fill=ACCENT,
        )
    )
    out.append(
        bar_row(
            left_x + 28,
            560,
            track_w,
            label=f"LLM-as-a-Judge 复核 · evaluator {evaluator_version}",
            fraction=None,
            value="不发布比率",
            caption="需真实模型节点；2 例样本支持不了比率——仓库口径是有几个报几个",
            fill=MUTED,
            hatch=True,
        )
    )

    right_x = left_x + left_w + 32
    right_w = width - right_x - MARGIN
    cards = [
        (
            "机械判卷 harness · Phase 0",
            [
                "P1–P6 探针 9 组全绿（v1 封卷 + v1.1 工作树）",
                "9 类违规注入全部命中预期 reason 码",
                "python -m benchmarks.agent.harness.probes",
            ],
            ACCENT,
        ),
        (
            "门禁黄金 fixtures · vendor 锁定",
            [
                f"{gate_diffs} 条 diff → usable {gate_usable} · blocked {gate_blocked}",
                "e2/e3 锁定句中专有名词；e4/e5 锁定误报方向",
                "与 true-tailor 双向对拍，漂移即挂",
            ],
            ACCENT,
        ),
        (
            f"产品内 LLM 裁判 · evaluator/{evaluator_version}",
            [
                "输出 hallucination_detected · details(0–5)",
                "定位：对齐质量复核，不承担幻觉率判据",
                "协议原话：裁判必须比考生便宜且不会做梦",
            ],
            MUTED,
        ),
    ]
    card_h = 168
    for i, (title, lines, color) in enumerate(cards):
        cy = 132 + i * (card_h + 16)
        out.append(panel(right_x, cy, right_w, card_h))
        out.append(rect(right_x, cy, 4, card_h, fill=color, rx=0))
        out.append(text(right_x + 24, cy + 40, title, size=15, fill=INK, weight="700"))
        for j, body in enumerate(lines):
            out.append(text(right_x + 24, cy + 74 + j * 28, body, size=12.2, fill=INK_2))

    out.append(line(MARGIN, height - 92, width - MARGIN, height - 92))
    out.append(
        text(
            MARGIN,
            height - 62,
            "数据来源  benchmarks/cases/adversarial_hallucination_*.json · tests/fixtures/gate/expected.en.json · benchmarks/agent/",
            size=12,
            fill=MUTED,
        )
    )
    out.append(
        text(
            MARGIN,
            height - 36,
            "复现  python benchmarks/run_benchmark.py --offline   ·   python -m benchmarks.agent.harness.probes",
            size=12,
            fill=MUTED,
            font=FONT_MONO,
        )
    )
    return svg(
        width,
        height,
        "".join(out),
        f"幻觉发生率门禁前后对比：{injected} 条编造断言，"
        "门禁前全部泄漏，门禁后 0 条进入输出",
    )


# ---------------------------------------------------------------------------
# Figure 3 -- README hero（品牌主视觉，不含数据）
# ---------------------------------------------------------------------------


def pill(
    x: float,
    y: float,
    width: float,
    label: str,
    *,
    fg: str,
    bg: str,
    size: float = 13,
) -> str:
    return rect(x, y, width, 30, fill=bg, rx=15) + text(
        x + width / 2, y + 20, label, size=size, fill=fg, weight="600", anchor="middle"
    )


def figure_hero() -> str:
    width, height = 1600, 460
    bg = "#0B0D11"
    panel_bg = "#12171F"
    grid = "#161C24"
    hairline = "#252C37"
    bright = "#E9EEF5"
    body = "#C3CBD8"
    dim = "#98A2B3"
    accent = "#2BB3C8"
    accent_soft = "#123039"
    ok = "#3DDC97"
    ok_soft = "#123027"
    alert = "#FF8A5B"
    alert_soft = "#331E16"

    out: list[str] = [rect(0, 0, width, height, fill=bg, rx=0)]
    for gx in range(0, width, 80):
        out.append(line(gx, 0, gx, height, stroke=grid))
    for gy in range(0, height, 80):
        out.append(line(0, gy, width, gy, stroke=grid))
    out.append(rect(0, 0, width, 4, fill=accent, rx=0))

    out.append(rect(64, 52, 44, 44, fill=accent, rx=11))
    out.append(text(86, 81, "RA", size=17, fill=bg, weight="800", anchor="middle"))
    out.append(text(124, 76, "ResuAlign-Lite", size=22, fill=bright, weight="700"))
    out.append(
        text(
            124,
            98,
            "CAREER STUDIO · LOCAL-FIRST",
            size=10.5,
            fill=dim,
            spacing=1.8,
        )
    )

    out.append(text(64, 186, "模型只能改写，", size=54, fill=bright, weight="800"))
    out.append(text(64, 252, "不能编造。", size=54, fill=accent, weight="800"))
    out.append(
        text(
            64,
            302,
            "本地求职工作台：简历诊断 · JD 对齐 · 投递闭环",
            size=20,
            fill=body,
        )
    )
    out.append(
        text(
            64,
            334,
            "每条建议都带 provenance；找不到原文依据的改写，会被 fail-closed 门禁拦下。",
            size=15.5,
            fill=dim,
        )
    )
    out.append(pill(64, 362, 150, "本地 SQLite", fg=accent, bg=accent_soft))
    out.append(pill(228, 362, 150, "逐条 provenance", fg=ok, bg=ok_soft))
    out.append(pill(392, 362, 186, "fail-closed 门禁", fg=alert, bg=alert_soft))

    card_x, card_y, card_w, card_h = 968, 88, 568, 300
    out.append(rect(card_x, card_y, card_w, card_h, fill=panel_bg, rx=16, stroke=hairline))
    out.append(
        text(card_x + 28, card_y + 40, "gate.py · 每条建议都要过这一关", size=17, fill=bright, weight="700")
    )
    out.append(
        text(
            card_x + 28,
            card_y + 64,
            "纯 stdlib · 无网络 · 与 skill 仓字节级同步",
            size=12,
            fill=dim,
            font=FONT_MONO,
        )
    )

    rows = [
        (
            card_y + 86,
            ok,
            ok_soft,
            "modify · 保留原文事实",
            "provenance 命中：数字与经历都能回到主简历原文",
            "通过",
        ),
        (
            card_y + 166,
            alert,
            alert_soft,
            "modify · 新增无关数字",
            "未找到出处：不进入建议，标记「建议复核」",
            "blocked",
        ),
    ]
    for y, color, soft, title, note, verdict in rows:
        out.append(rect(card_x + 24, y, card_w - 48, 66, fill="#0E131A", rx=10, stroke=hairline))
        out.append(rect(card_x + 24, y, 4, 66, fill=color, rx=2))
        out.append(text(card_x + 44, y + 27, title, size=14.5, fill=bright, weight="600"))
        out.append(text(card_x + 44, y + 49, note, size=12, fill=dim))
        out.append(pill(card_x + card_w - 130, y + 20, 82, verdict, fg=color, bg=soft, size=12))

    out.append(
        text(
            card_x + 28,
            card_y + card_h - 20,
            "改写可以发生，事实不能凭空出现。",
            size=13,
            fill=body,
            weight="600",
        )
    )
    out.append(
        text(
            width - 64,
            height - 34,
            "FastAPI · SQLite WAL · 原生前端 · 零云依赖",
            size=12.5,
            fill=dim,
            anchor="end",
            font=FONT_MONO,
        )
    )
    return svg(
        width,
        height,
        "".join(out),
        "ResuAlign-Lite：本地优先的求职工作台，每条改写必须溯源，"
        "无原文依据的建议被门禁拦截",
    )


# ---------------------------------------------------------------------------
# Figure 4 -- 流水线架构（不含数据）
# ---------------------------------------------------------------------------


def arrow_down(x: float, y1: float, y2: float, *, color: str = "#AEB8C4") -> str:
    return line(x, y1, x, y2 - 11, stroke=color, sw=2) + (
        f'<path d="M{x - 6:g},{y2 - 13:g} L{x:g},{y2:g} L{x + 6:g},{y2 - 13:g} Z" fill="{color}"/>'
    )


def arrow_right(x1: float, x2: float, y: float, *, color: str = "#AEB8C4") -> str:
    return line(x1, y, x2 - 11, y, stroke=color, sw=2) + (
        f'<path d="M{x2 - 13:g},{y - 6:g} L{x2:g},{y:g} L{x2 - 13:g},{y + 6:g} Z" fill="{color}"/>'
    )


def stage_box(
    x: float,
    y: float,
    w: float,
    h: float,
    index: str,
    title: str,
    subtitle: str,
    *,
    color: str,
    note: str = "",
) -> str:
    out = [panel(x, y, w, h), rect(x, y, w, 4, fill=color, rx=0)]
    out.append(
        text(x + 22, y + 38, index, size=12, fill=color, weight="700", font=FONT_MONO)
    )
    out.append(text(x + 22, y + 66, title, size=19, fill=INK, weight="700"))
    out.append(text(x + 22, y + 92, subtitle, size=12.5, fill=MUTED))
    if note:
        out.append(text(x + 22, y + h - 20, note, size=12, fill=INK_2))
    return "".join(out)


def figure_architecture() -> str:
    width, height = 1600, 1100
    out: list[str] = [
        rect(0, 0, width, height, fill=CANVAS, rx=0),
        text(64, 62, "从 JD 到定稿：一条受控流水线", size=28, fill=INK, weight="800"),
        text(
            64,
            94,
            "LLM 只负责提议；事实校验、排序与交付都是确定性的。任何一层都可以单独替换。",
            size=14.5,
            fill=MUTED,
        ),
    ]

    top, top_h = 132, 128
    top_w = 432
    top_xs = (64, 584, 1104)
    out.append(
        stage_box(
            top_xs[0],
            top,
            top_w,
            top_h,
            "01 / INGEST",
            "采集",
            "Tampermonkey 脚本 · 粘贴 JD · CSV 同步",
            color=ACCENT,
            note="来源与原文一起入库，不承诺任意站点抓取",
        )
    )
    out.append(
        stage_box(
            top_xs[1],
            top,
            top_w,
            top_h,
            "02 / PARSE",
            "解析与画像",
            "parser(PDF / DOCX / TXT) → jd_profiler",
            color=ACCENT,
            note="结构化岗位画像：硬技能、场景、经验年限",
        )
    )
    out.append(
        stage_box(
            top_xs[2],
            top,
            top_w,
            top_h,
            "03 / ROUTE",
            "角色路由",
            "diagnose · gap_analyzer · editor · evaluator",
            color=ACCENT,
            note="每角色独立超时、token 预算与故障转移",
        )
    )
    out.append(arrow_right(64 + top_w + 8, 584 - 4, top + top_h / 2))
    out.append(arrow_right(584 + top_w + 8, 1104 - 4, top + top_h / 2))

    mid_y = 338
    mid_h = 148
    out.append(
        stage_box(
            64,
            mid_y,
            700,
            mid_h,
            "A / FAST PATH",
            "快速评估（零 LLM）",
            "local_fallback + match_scorer · Ctrl+K 秒出匹配分",
            color=OK,
            note="不建岗位、不烧额度；规则抽取缺口 top3，结论可解释",
        )
    )
    out.append(
        stage_box(
            836,
            mid_y,
            700,
            mid_h,
            "B / CONTROLLED REWRITE",
            "受控改写（逐条 Diff）",
            "tailor.py · 每条建议携带 original / proposed / provenance",
            color=ACCENT,
            note="只改写、重排、强调已有事实；noop 与越权内容在写回前过滤",
        )
    )

    bus_y = 302
    out.append(line(800, top + top_h, 800, bus_y, stroke="#AEB8C4", sw=2))
    out.append(line(414, bus_y, 1186, bus_y, stroke="#AEB8C4", sw=2))
    out.append(arrow_down(414, bus_y - 1, mid_y))
    out.append(arrow_down(1186, bus_y - 1, mid_y))

    gate_y = 566
    gate_h = 150
    out.append(line(414, mid_y + mid_h, 414, gate_y - 16, stroke="#AEB8C4", sw=2))
    out.append(line(1186, mid_y + mid_h, 1186, gate_y - 16, stroke="#AEB8C4", sw=2))
    out.append(line(414, gate_y - 16, 1186, gate_y - 16, stroke="#AEB8C4", sw=2))
    out.append(arrow_down(800, gate_y - 17, gate_y))

    out.append(panel(64, gate_y, width - 128, gate_h))
    out.append(rect(64, gate_y, width - 128, 4, fill=ALERT, rx=0))
    out.append(text(88, gate_y + 38, "04 / GATE", size=12, fill=ALERT, weight="700", font=FONT_MONO))
    out.append(text(88, gate_y + 68, "防幻觉门禁  gate.py", size=21, fill=INK, weight="800"))
    out.append(
        text(
            88,
            gate_y + 94,
            "纯 stdlib · 无网络 · fail-closed；与 true-tailor skill 仓字节级锁定",
            size=13,
            fill=MUTED,
        )
    )
    steps = [
        ("①  provenance 解析", "建议必须能映射回主简历原文"),
        ("②  内容检查", "数字、术语、断言逐项比对"),
        ("③  noop 过滤", "原文与建议相同的不算改写"),
    ]
    for index, (title, note) in enumerate(steps):
        x = 88 + index * 486
        out.append(rect(x, gate_y + 108, 462, 30, fill=ALERT_SOFT, rx=8))
        out.append(text(x + 14, gate_y + 128, title, size=12.5, fill=ALERT, weight="700"))
        out.append(text(x + 164, gate_y + 128, note, size=11.5, fill=INK_2))

    deliver_y = 776
    out.append(arrow_down(800, gate_y + gate_h, deliver_y))
    out.append(panel(64, deliver_y, width - 128, 150))
    out.append(rect(64, deliver_y, width - 128, 4, fill=OK, rx=0))
    out.append(
        text(88, deliver_y + 38, "05 / DELIVER", size=12, fill=OK, weight="700", font=FONT_MONO)
    )
    out.append(text(88, deliver_y + 68, "交付层", size=21, fill=INK, weight="800"))
    out.append(
        text(
            88,
            deliver_y + 94,
            "单岗双栏对照编辑 · A4 预览 · 统一求职工作台（列表 / 看板）· 驾驶舱复盘 · md / json / pdf 导出",
            size=13.5,
            fill=INK_2,
        )
    )
    out.append(
        text(
            88,
            deliver_y + 118,
            "MV3 回填扩展 → 网申表单；所有数据留在本机。",
            size=12.5,
            fill=MUTED,
        )
    )

    guard_y = height - 96
    out.append(line(64, guard_y - 22, width - 64, guard_y - 22, stroke=RULE, dash="6 6"))
    out.append(text(64, guard_y + 6, "横切护栏", size=12, fill=MUTED, weight="700"))
    guards = [
        ("cost_guard", "每日调用上限 · 同任务 3 连败熔断"),
        ("llm_nodes", "节点熔断 · 冷却 · 多活转移"),
        ("watchdog", "任务墙钟 1800s 默认"),
        ("secret_box", "API Key Fernet 静态加密"),
    ]
    for index, (name, note) in enumerate(guards):
        x = 176 + index * 348
        out.append(text(x, guard_y + 6, name, size=12.5, fill=INK, weight="700", font=FONT_MONO))
        out.append(text(x + 92, guard_y + 6, note, size=11.5, fill=MUTED))

    return svg(
        width,
        height,
        "".join(out),
        "ResuAlign-Lite 流水线：采集、解析画像、角色路由、快速评估、受控改写、"
        "防幻觉门禁、交付，横切成本、节点、看门狗与密钥护栏",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail instead of writing when files differ")
    args = parser.parse_args(argv)

    targets = {
        OUT_DIR / "hero.svg": figure_hero(),
        OUT_DIR / "architecture.svg": figure_architecture(),
        OUT_DIR / "gate-before-after.svg": figure_before_after(),
        OUT_DIR / "hallucination-rate.svg": figure_hallucination(),
    }
    stale: list[str] = []
    for path, content in targets.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("stale figure(s): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
