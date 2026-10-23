#!/usr/bin/env python3
"""结构债项目的视觉基线采集/对比（Phase 0）。

为什么需要：CSS 合并与 token 清理最容易「测试全绿但界面悄悄变样」。先用
Playwright 把 6 条主路由 × 明暗 × 桌面/手机 截成固定尺寸图，后续每个阶段
用 `--compare` 对比同一批文件，超过阈值的差异必须人工确认。

用法（需要本地服务已启动，默认 127.0.0.1:8000）：
    python scripts/visual_baseline.py --tag baseline
    python scripts/visual_baseline.py --tag after --compare

输出：
    tests/visual/<tag>/<theme>-<width>-<route>.png
    tests/visual/<tag>/manifest.json   （sha256 + 尺寸）
    tests/visual/<tag>/diff-report.json（--compare 时）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "tests" / "visual"
BASE = "http://127.0.0.1:8000"
ROUTES = [
    ("dashboard", "#/dashboard"),
    ("review", "#/review"),
    ("jobs", "#/jobs"),
    ("resume-list", "#/resume/list"),
    ("settings", "#/settings"),
]
VIEWPORTS = [(1440, 900, "desktop"), (390, 844, "mobile")]
THEMES = ["light", "dark"]
DIFF_THRESHOLD = 0.002  # 0.2% 像素差异以内视为无变化


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--compare", action="store_true")
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def capture(tag: str) -> dict:
    out_dir = OUT_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"tag": tag, "shots": {}, "errors": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in THEMES:
            for width, height, label in VIEWPORTS:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                )
                context.add_init_script(
                    f"try {{ localStorage.setItem('resualign_theme', '{theme}'); }} catch (e) {{}}"
                )
                page = context.new_page()
                page.on(
                    "console",
                    lambda msg: manifest["errors"].append(f"{theme}/{label}: {msg.text}")
                    if msg.type == "error"
                    else None,
                )
                for name, route in ROUTES:
                    page.goto(f"{BASE}{route}", wait_until="domcontentloaded")
                    try:
                        page.wait_for_function(
                            "() => !document.querySelector('[data-view-skeleton]')",
                            timeout=20000,
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(2200)
                    path = out_dir / f"{theme}-{label}-{name}.png"
                    page.screenshot(path=str(path))
                    with Image.open(path) as image:
                        manifest["shots"][path.name] = {
                            "sha256": sha256(path),
                            "width": image.width,
                            "height": image.height,
                        }
                context.close()
        browser.close()
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def compare(tag: str) -> int:
    before_dir = OUT_ROOT / "baseline"
    after_dir = OUT_ROOT / tag
    report = {"compared": [], "changed": [], "missing": []}
    for shot in sorted((before_dir).glob("*.png")):
        current = after_dir / shot.name
        if not current.exists():
            report["missing"].append(shot.name)
            continue
        with Image.open(shot) as a, Image.open(current) as b:
            if a.size != b.size:
                report["changed"].append(
                    {"shot": shot.name, "reason": f"size {a.size} -> {b.size}", "ratio": 1.0}
                )
                continue
            diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
            histogram = diff.convert("L").histogram()
            total = a.width * a.height
            changed = sum(count for value, count in enumerate(histogram) if value > 8)
            ratio = changed / total
            report["compared"].append({"shot": shot.name, "ratio": round(ratio, 5)})
            if ratio > DIFF_THRESHOLD:
                report["changed"].append({"shot": shot.name, "ratio": round(ratio, 5)})
    (after_dir / "diff-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["changed"] or report["missing"] else 0


if __name__ == "__main__":
    parsed = parse_args(sys.argv[1:])
    BASE = parsed.base
    if parsed.compare:
        sys.exit(compare(parsed.tag))
    manifest = capture(parsed.tag)
    print(f"captured {len(manifest['shots'])} shots -> {OUT_ROOT / parsed.tag}")
    if manifest["errors"]:
        print(f"console errors: {len(manifest['errors'])}")
        sys.exit(1)
