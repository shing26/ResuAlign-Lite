"""Render the #113 probe video: a terminal replay of a real gate run.

ADR-0041 决定 7 / issue #113: a <=90s clip that shows the verifier blocking a
fabricated diff on camera. This is a *replay*, not a screen recording: every
line shown was captured from the commands in SEQUENCE (run against
truetailor/examples/demoflow, the synthetic resume + synthetic JD), and the
script re-runs them so the frames cannot drift from reality.

Needs Pillow + a local ffmpeg. Output: <repo>/docs/gate-demo.mp4 in the
truetailor checkout.

    python scripts/probe_video.py --out D:/truetailor/docs/gate-demo.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 720
FONT_PATH = Path("C:/Windows/Fonts/consola.ttf")
FONT_SIZE = 21
LINE_H = 28
MARGIN_X = 34
MARGIN_Y = 26
BG = (12, 15, 19)
FG = (214, 222, 232)
DIM = (126, 138, 152)
PROMPT = (108, 196, 145)
OK = (126, 209, 138)
BLOCK = (232, 96, 88)
GATE = (245, 203, 92)
FPS = 20


@dataclass
class Event:
    """One renderable step: typed keystrokes, an instant line, or a pause."""

    kind: str  # "type" | "line" | "wait" | "clear"
    text: str = ""
    color: tuple = FG
    rate: float = 34.0  # chars per second for "type"
    seconds: float = 0.0  # duration for "wait"


def build_sequence(skill_repo: Path) -> list[Event]:
    """Produce the timeline AND re-run the real commands to verify the text."""

    def run(args: list[str]) -> str:
        proc = subprocess.run(
            [sys.executable, *args],
            cwd=skill_repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if proc.returncode != 0:
            raise SystemExit(f"replay command failed: {args}\n{proc.stderr}")
        return proc.stdout

    gate1 = run(
        [
            "gate.py",
            "--resume", "examples/demoflow/resume.md",
            "--diffs", "examples/demoflow/diffs.round1.json",
            "--allowlist", "examples/demoflow/gap.json",
        ]
    ).splitlines()
    applied = run(
        [
            "apply.py",
            "--resume", "examples/demoflow/resume.md",
            "--diffs", "examples/demoflow/diffs.round1.json",
            "--allowlist", "examples/demoflow/gap.json",
            "--accept", "demo-d1-service-ownership",
            "--accept", "demo-d2-latency-slo",
            "--accept", "demo-d3-runbooks-salvaged",
            "--accept", "demo-d7-load-testing",
            "--accept", "demo-d4-fabricated-throughput",
            "--out", "examples/demoflow/resume.r1.md",
        ]
    ).splitlines()
    gate2 = run(
        [
            "gate.py",
            "--resume", "examples/demoflow/resume.r1.md",
            "--diffs", "examples/demoflow/diffs.round2.json",
            "--allowlist", "examples/demoflow/gap.json",
        ]
    ).splitlines()
    checks = run(["selftest.py"]).splitlines()

    events: list[Event] = []

    def cmd(line: str) -> None:
        events.append(Event("type", f"PS D:\\work> {line}", PROMPT))
        events.append(Event("wait", seconds=0.35))

    def cont(line: str, last: bool = False) -> None:
        events.append(Event("type", f"{'> ' if last else '>> '} {line}", PROMPT))
        events.append(Event("wait", seconds=0.3))

    def out(lines: list[str], pause_after: float = 0.25) -> None:
        for line in lines:
            if not line.strip():
                continue
            color = FG
            if line.startswith("BLOCK") or "FAILED" in line:
                color = BLOCK
            elif line.startswith("OK ") or line.startswith("  ok "):
                color = OK
            elif line.startswith("GATE:"):
                color = GATE
            elif line.startswith("refused") or line.startswith("  - "):
                color = DIM
            events.append(Event("line", line, color))
        events.append(Event("wait", seconds=pause_after))

    events.append(Event("line", "true-tailor - resume tailoring where the", GATE))
    events.append(Event("line", "fabrication gate is code, not a promise", GATE))
    events.append(Event("line", "# synthetic resume, synthetic JD, real gate", DIM))
    events.append(Event("wait", seconds=2.0))
    events.append(Event("clear"))

    cmd("python gate.py --resume examples/demoflow/resume.md \\")
    cont("      --diffs examples/demoflow/diffs.round1.json \\")
    cont("      --allowlist examples/demoflow/gap.json", last=True)
    events.append(Event("wait", seconds=0.9))
    out(gate1, pause_after=1.2)

    block_lines = [line for line in gate1 if line.startswith("BLOCK")]
    events.append(Event("line", "# three of the model's suggestions are now:", DIM))
    events.append(
        Event(
            "line",
            "#   {n} invented tool, {m} invented metric,".format(
                n=sum(1 for b in block_lines if "term" in b),
                m=sum(1 for b in block_lines if "number" in b),
            ),
            DIM,
        )
    )
    events.append(Event("line", "#   and 1 no-op that only looked like work", DIM))
    events.append(Event("wait", seconds=2.6))
    events.append(Event("clear"))

    cmd("python apply.py --resume examples/demoflow/resume.md \\")
    cont("      --diffs examples/demoflow/diffs.round1.json \\")
    cont("      --accept demo-d1-service-ownership ... \\")
    cont("      --accept demo-d4-fabricated-throughput \\")
    cont("      --out examples/demoflow/resume.r1.md", last=True)
    events.append(Event("wait", seconds=0.9))
    out(applied, pause_after=1.0)
    events.append(Event("line", "# the blocked diff is refused at write time", DIM))
    events.append(Event("wait", seconds=2.4))
    events.append(Event("clear"))

    cmd("python gate.py --resume examples/demoflow/resume.r1.md \\")
    cont("      --diffs examples/demoflow/diffs.round2.json \\")
    cont("      --log examples/demoflow/tailoring.jsonl \\")
    cont("      --round 2 --trigger eval:round1", last=True)
    events.append(Event("wait", seconds=0.9))
    out(gate2, pause_after=1.0)
    events.append(
        Event("line", "# round 2 ran against the edited candidate, not the master", DIM)
    )
    events.append(Event("wait", seconds=2.0))
    events.append(Event("clear"))

    cmd("python selftest.py")
    events.append(Event("wait", seconds=0.7))
    tail = [line for line in checks if line.strip()][-9:]
    out(tail, pause_after=0.8)
    events.append(Event("line", "# the rules above are the spec, not the prose", DIM))
    events.append(Event("wait", seconds=2.2))
    events.append(Event("clear"))

    cmd("cat examples/demoflow/tailoring.jsonl")
    events.append(Event("wait", seconds=0.6))
    for line in (skill_repo / "examples/demoflow/tailoring.jsonl").read_text(
        encoding="utf-8"
    ).splitlines():
        entry = json.loads(line)
        out(
            [
                "round {r}  trigger={t}  diffs={d}  usable={u}  blocked={b}".format(
                    r=entry["round"],
                    t=entry["trigger"],
                    d=entry["diffs"],
                    u=entry["usable"],
                    b=json.dumps(entry["blocked"]),
                ),
                "       resume-sha256={h}  chain={c}".format(
                    h=entry["resume_sha256"][:12],
                    c=json.dumps(entry["chain"]),
                ),
            ],
            pause_after=0.5,
        )
    events.append(Event("wait", seconds=1.2))
    events.append(Event("line", "# one line per gated run, and it cannot be", DIM))
    events.append(Event("line", "# back-dated: round 2 cites round 1, and the", DIM))
    events.append(Event("line", "# resume hash changed underneath it", DIM))
    events.append(Event("wait", seconds=2.0))
    events.append(Event("clear"))

    # Freeze frame: the round-1 summary, verbatim, because that is the run the
    # repo exists for. ADR-0041 决定 7 asks for the gate line to be readable
    # and still on screen when the clip stops.
    events.append(Event("line", "# round 1, pasted verbatim, not restated:", DIM))
    events.append(Event("wait", seconds=0.4))
    events.append(Event("line", gate1[-1], GATE))
    events.append(Event("wait", seconds=0.5))
    events.append(
        Event("line", "# the fabrication gate is code, not a promise", DIM)
    )
    events.append(Event("wait", seconds=7.0))  # hold the summary line
    return events


def render(events: list[Event], frames_dir: Path) -> tuple[int, float]:
    """Walk the timeline at fixed FPS and write one PNG per frame."""
    font = ImageFont.truetype(str(FONT_PATH), FONT_SIZE)
    small = ImageFont.truetype(str(FONT_PATH), FONT_SIZE - 4)
    rows = (HEIGHT - 2 * MARGIN_Y) // LINE_H
    screen: list[tuple[str, tuple]] = []
    frames = 0

    def paint(typed: str | None) -> None:
        nonlocal frames
        image = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(image)
        visible = screen[-rows:]
        y = MARGIN_Y
        for text, color in visible:
            draw.text((MARGIN_X, y), text, font=font, fill=color)
            y += LINE_H
        if typed is not None:
            draw.text((MARGIN_X, y), typed, font=font, fill=PROMPT)
            cursor_x = MARGIN_X + draw.textlength(typed, font=font)
            draw.rectangle(
                [cursor_x + 2, y + 3, cursor_x + 13, y + LINE_SIZE_OFFSET],
                fill=PROMPT,
            )
            y += LINE_H
        draw.text(
            (MARGIN_X, HEIGHT - MARGIN_Y + 4),
            "terminal replay of a real run - examples/demoflow - nothing here is a mock",
            font=small,
            fill=(84, 94, 106),
        )
        image.save(frames_dir / f"{frames:05d}.png")
        frames += 1

    for event in events:
        if event.kind == "clear":
            for _ in range(2):
                paint(None)
            screen.clear()
            continue
        if event.kind == "line":
            for text in wrap(event.text, WIDTH - 2 * MARGIN_X, font):
                screen.append((text, event.color))
            paint(None)
            continue
        if event.kind == "type":
            steps = max(1, int(len(event.text) / event.rate * FPS))
            for step in range(1, steps + 1):
                cut = round(len(event.text) * step / steps)
                paint(event.text[:cut])
            screen.append((event.text, event.color))
            continue
        if event.kind == "wait":
            for _ in range(max(1, int(event.seconds * FPS))):
                paint(None)
    return frames, frames / FPS


LINE_SIZE_OFFSET = LINE_H - 6


def wrap(text: str, max_width: int, font) -> list[str]:
    """Hard-wrap to the terminal width so nothing renders off-screen."""
    probe = Image.new("RGB", (8, 8))
    width = ImageDraw.Draw(probe).textlength(text, font=font)
    if width <= max_width or not text:
        return [text] or [""]
    limit = int(max_width * len(text) / width)
    limit = max(20, limit)
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def encode(frames_dir: Path, out_path: Path, fps: int = FPS) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not on PATH; frames are in " + str(frames_dir))
    command = [
        ffmpeg,
        "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "%05d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-crf", "23",
        "-preset", "medium",
        "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(command, check=True, capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo",
        default="D:/truetailor",
        help="checkout of the truetailor skill repo",
    )
    parser.add_argument("--out", default="D:/truetailor/docs/gate-demo.mp4")
    parser.add_argument("--keep-frames", default="", help="write PNGs here instead of a temp dir")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    keep = Path(args.keep_frames) if args.keep_frames else None
    frames_dir = keep or Path(tempfile.mkdtemp(prefix="truetailor-frames-"))
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("*.png"):
        stale.unlink()

    events = build_sequence(repo)
    count, seconds = render(events, frames_dir)
    print(f"{count} frames, {seconds:.1f}s at {FPS}fps -> encoding")
    encode(frames_dir, out_path)
    print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    if keep is None:
        shutil.rmtree(frames_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
