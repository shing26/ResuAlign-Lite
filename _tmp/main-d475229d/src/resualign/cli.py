import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import colorama

from .config import build_config
from .engine import run

colorama.init()


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="ResuAlign - Resume alignment and diagnosis tool"
    )
    p.add_argument("resume", type=Path, nargs="?", help="Path to resume file (PDF/DOCX/txt)")
    jd_group = p.add_mutually_exclusive_group()
    jd_group.add_argument("--jd", "-j", help="Job description text (inline)")
    jd_group.add_argument("--jd-file", type=Path, help="Path to job description file")
    jd_group.add_argument("--jd-url", help="URL of a job description page to crawl")
    agent_group = p.add_mutually_exclusive_group()
    agent_group.add_argument(
        "--headless",
        action="store_true",
        help="Run the agent-native headless daemon (no web frontend)",
    )
    agent_group.add_argument(
        "--agent-mode",
        action="store_true",
        help="Alias for --headless: run the agent-native daemon",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Headless/agent-mode poll interval in seconds (default: 30)",
    )
    p.add_argument("--provider", help="LLM provider (deepseek/openrouter/ollama)")
    p.add_argument("--api-key", help="API key (overrides .env/env)")
    p.add_argument("--model", "-m", help="Model name")
    p.add_argument(
        "--output-dir", type=Path, default=Path.cwd(),
        help="Directory for JSON report (default: current dir)",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only print score and report path (no detail output)",
    )
 
    return p.parse_args(argv)


def _colorize_score(score: int) -> str:
    if score >= 80:
        return f"\x1b[92m{score}\x1b[0m"
    elif score >= 50:
        return f"\x1b[93m{score}\x1b[0m"
    else:
        return f"\x1b[91m{score}\x1b[0m"


def main(argv=None):
    args = _parse_args(argv)

    # Agent-native mode: run the headless daemon instead of the interactive
    # resume-vs-JD report. No resume file, no web frontend.
    if args.headless or args.agent_mode:
        from .agent.headless import run_headless

        run_headless(interval=args.interval)
        return

    if args.resume is None:
        print(
            "Error: resume file is required "
            "(or use --headless/--agent-mode for the agent daemon).",
            file=sys.stderr,
        )
        sys.exit(2)

    config = build_config(
        provider=args.provider,
        api_key=args.api_key,
        model=args.model,
    )

    if not config.is_llm_configured:
        print(
            "Error: LLM not configured. Set via --api-key, .env file, "
            f"or {config.provider.upper()}_API_KEY environment variable, "
            "or switch to Ollama local node.",
            file=sys.stderr,
        )
        sys.exit(1)

    t0 = time.monotonic()

    try:
        from .parser import extract_text
        resume_text = extract_text(args.resume)
    except Exception as e:
        print(f"Error reading resume: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] {len(resume_text)} chars extracted from {args.resume.name}")

    jd_text = None
    if args.jd_url:
        try:
            from .crawler import CrawlError, crawl_jd
            jd_text = crawl_jd(args.jd_url)
        except CrawlError as e:
            print(f"Error fetching JD from URL: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"[OK] JD: {len(jd_text)} chars from URL")
    elif args.jd_file:
        try:
            jd_text = args.jd_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error reading JD file: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"[OK] JD: {len(jd_text)} chars from {args.jd_file.name}")
    elif args.jd:
        jd_text = args.jd
        print(f"[OK] JD: {len(jd_text)} chars (inline)")

    def on_stage(stage, message):
        if not args.quiet:
            print(f"[{stage}] {message}", file=sys.stderr)

    report = run(config, resume_text, jd_text, on_stage=on_stage)
    report.elapsed_seconds = round(time.monotonic() - t0, 1)

    # Terminal output
    colored_score = _colorize_score(report.score)
    print(f"Score: {colored_score} /100")

    if not args.quiet:
        skills_str = ",".join(report.skills[:10]) if report.skills else "none"
        print(f"Skills: {skills_str}")
        if report.issues:
            for i in report.issues:
                print(f"  ! {i}")
        if report.diffs:
            sep = "-" * 50
            for i, d in enumerate(report.diffs, 1):
                if i > 1:
                    print(f"  {sep}")
                tag = f" [{d.confidence.upper()}]" if d.confidence else " [MEDIUM]"
                print(f"  #{i}{tag} {d.reason}")
                if d.original:
                    print(f"    - {d.original[:120]}")
                print(f"    + {d.proposed[:120]}")
        print(f"Time: {report.elapsed_seconds}s | Model: {config.model}")
 
    # JSON output
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"resualign-report-{ts}.json"

    report_dict = asdict(report)
    json_path.write_text(
        json.dumps(report_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[OK] Report saved: {json_path}")


if __name__ == "__main__":
    main()
