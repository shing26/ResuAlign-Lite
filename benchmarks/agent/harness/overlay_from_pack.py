"""Extract the v1.1 fixture overlay rows from the input pack into .scratch/phase0/.

Until the user commits v1.1 into `fixtures/phase0_q4_v1.jsonl`, the harness needs
those rows to test its own rules. This reads the pack markdown and drops the
overlay lines into the gitignored .scratch area - it never writes the fixture.

    python -m benchmarks.agent.harness.overlay_from_pack [pack.md]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .core import AGENT_DIR

PACK_DEFAULT = Path("D:/phase0-v1.1-输入包-2026-09-14.md")
OUT = AGENT_DIR.parent.parent / ".scratch" / "phase0" / "v11_overlay.jsonl"
KINDS = {"_meta", "ss", "md", "bs", "sb"}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    pack = Path(argv[0]) if argv else PACK_DEFAULT
    if not pack.exists():
        print(f"pack not found: {pack}", file=sys.stderr)
        return 2
    text = pack.read_text(encoding="utf-8")
    rows: list[dict] = []
    for block in re.findall(r"```jsonl\s*(.*?)```", text, re.S):
        for line in block.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            obj = json.loads(line)
            if obj.get("kind") in KINDS:
                rows.append(obj)
    if not rows:
        print("no overlay rows found", file=sys.stderr)
        return 3
    seen: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["kind"], r.get("id") or r.get("name"))
        seen[key] = r
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in seen.values()) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(seen)} overlay rows -> {OUT}")
    print("ids:", ",".join(k[1] for k in seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
