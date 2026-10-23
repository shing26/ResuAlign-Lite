#!/usr/bin/env python3
"""元素级计算样式快照 / 对比（结构债 Phase 2b 验证工具）。

为什么比截图更强：截图只能看到默认状态、且像素差异掩盖「哪个属性变了」。
这里对 5 条路由 × 明暗 × 桌面/手机 的每个元素记录 ~35 个计算属性，
CSS 重构后逐元素对比，任何级联变化都会以「元素 + 属性 + before/after」列出。

用法（需要本地服务）：
    python scripts/style_snapshot.py --tag before
    python scripts/style_snapshot.py --tag after --compare
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / ".scratch" / "style-snapshots"
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

PROPS = [
    "display", "position", "top", "right", "bottom", "left", "z-index",
    "width", "height", "min-width", "min-height", "max-width", "max-height",
    "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "gap", "row-gap", "column-gap", "flex", "flex-direction", "flex-wrap",
    "align-items", "justify-content", "grid-template-columns", "grid-template-rows",
    "color", "background-color", "background-image", "border-top-width",
    "border-right-width", "border-bottom-width", "border-left-width",
    "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
    "border-radius", "box-shadow", "opacity", "overflow-x", "overflow-y",
    "font-family", "font-size", "font-weight", "line-height", "letter-spacing",
    "text-transform", "text-align", "visibility",
]

JS = """
(props) => {
  const out = [];
  const walk = (element, path) => {
    const style = getComputedStyle(element);
    const values = {};
    for (const prop of props) values[prop] = style.getPropertyValue(prop);
    out.push({
      path,
      tag: element.tagName.toLowerCase(),
      cls: String(element.className || "").slice(0, 120),
      values,
    });
    for (let index = 0; index < element.children.length; index += 1) {
      walk(element.children[index], `${path}>${element.children[index].tagName.toLowerCase()}:${index}`);
    }
  };
  if (document.body) walk(document.body, "body");
  return out;
}
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--tag", default="before")
    parser.add_argument("--compare", action="store_true")
    return parser.parse_args(argv)


def capture(tag: str, base: str) -> dict:
    out_dir = OUT_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"tag": tag, "pages": {}, "errors": []}
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
                    page.goto(f"{base}{route}", wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    elements = page.evaluate(JS, PROPS)
                    manifest["pages"][f"{theme}-{label}-{name}"] = elements
                context.close()
        browser.close()
    (out_dir / "snapshot.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def compare(tag: str) -> int:
    before = json.loads((OUT_ROOT / "before" / "snapshot.json").read_text(encoding="utf-8"))
    after = json.loads((OUT_ROOT / tag / "snapshot.json").read_text(encoding="utf-8"))
    report = {"pages": {}, "changedElements": 0}
    for page_name, before_elements in before["pages"].items():
        after_elements = after["pages"].get(page_name)
        if after_elements is None:
            report["pages"][page_name] = {"error": "missing page"}
            continue
        changes = []
        limit = min(len(before_elements), len(after_elements))
        if len(before_elements) != len(after_elements):
            changes.append(
                {
                    "element": "<page>",
                    "prop": "element-count",
                    "before": len(before_elements),
                    "after": len(after_elements),
                }
            )
        for index in range(limit):
            before_element = before_elements[index]
            after_element = after_elements[index]
            if before_element["path"] != after_element["path"]:
                changes.append(
                    {
                        "element": before_element["path"],
                        "prop": "path",
                        "before": before_element["path"],
                        "after": after_element["path"],
                    }
                )
                continue
            for prop, before_value in before_element["values"].items():
                after_value = after_element["values"].get(prop)
                if before_value != after_value:
                    changes.append(
                        {
                            "element": before_element["path"],
                            "cls": before_element["cls"],
                            "prop": prop,
                            "before": before_value,
                            "after": after_value,
                        }
                    )
        report["changedElements"] += len(changes)
        if changes:
            report["pages"][page_name] = changes
    (OUT_ROOT / tag / "diff.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "pages"}, ensure_ascii=False))
    for page_name, changes in report["pages"].items():
        print(f"{page_name}: {len(changes)} changes")
        for change in changes[:3]:
            print("  ", json.dumps(change, ensure_ascii=False)[:220])
    return 1 if report["changedElements"] else 0


if __name__ == "__main__":
    parsed = parse_args(sys.argv[1:])
    if parsed.compare:
        sys.exit(compare(parsed.tag))
    manifest = capture(parsed.tag, parsed.base)
    print(f"captured {len(manifest['pages'])} pages -> {OUT_ROOT / parsed.tag}")
    print(f"console errors: {len(manifest['errors'])}")
