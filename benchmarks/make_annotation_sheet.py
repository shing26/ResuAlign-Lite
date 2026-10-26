"""ADR-0065 A1: generate the human annotation sheet (read-only, reproducible).

Usage:
  python benchmarks/make_annotation_sheet.py --resume-a <id> --resume-b <id>

Sampling is stratified by job_function with fixed quotas; within a family the
order is sha256(SEED + job_id), so the same seed always yields the same sheet.
The DB is opened read-only: this script never writes to data/jobs.db.

Deliberately excluded from the sheet: match_score, usable_diffs, model output and
any prior ranking. Annotation must be blind to existing scores (design 11.1).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

SEED = "adr-0065-a1-v1"
EXCERPT_CHARS = 200

# 50 items: backend-heavy (the two resumes are Java/AI-app), with other families
# kept as discriminative negatives.
DEFAULT_QUOTAS = {
    "后端": 32,
    "算法": 8,
    "数据": 4,
    "测试": 3,
    "产品": 2,
    "运营": 1,
}
# 未分类（<空>）的 8 条在库内正文多为作者自带笔记而非 JD 原文，混入会污染
# 标注质量，故整族排除；配额并入「后端」（两份简历的主方向）。


def connect_readonly(db_path: str) -> sqlite3.Connection:
    uri = "file:" + Path(db_path).resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def order_key(job_id: str) -> str:
    return hashlib.sha256((SEED + "|" + job_id).encode("utf-8")).hexdigest()


def flatten_excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """First chars of the *actual JD body*, not the ingest metadata header.

    jd_text rows start with a capture header ("# 178 · company · title",
    "> 抓取日 …", source URL). Those lines would eat the whole excerpt and tell
    the annotator nothing new, so they are dropped before flattening.
    """
    kept = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ">", "|", "\u2514", "\u251c")):
            continue
        if stripped.startswith("抓取日") or stripped.startswith("来源"):
            continue
        if set(stripped) <= set("-=*_ |"):  # markdown rule / separator noise
            continue
        kept.append(stripped)
    flat = " ".join(kept) if kept else " ".join((text or "").split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def requirement_summary(profile_json: str | None, jd_text: str) -> str:
    """Compact, blind-to-scores view of what the posting asks for.

    Uses the stored structured profile when present (293/329 rows), because the
    raw jd_text often carries the author's own ingest notes and markdown rules.
    """
    parts: list[str] = []
    try:
        profile = json.loads(profile_json) if profile_json else {}
    except (TypeError, ValueError):
        profile = {}
    if isinstance(profile, dict):
        skills = (
            profile.get("must_have_skills")
            or profile.get("required_skills")
            or profile.get("skills")
            or []
        )
        if skills:
            parts.append("要求：" + "、".join(str(s) for s in skills[:8])[:110])
        scenes = (
            profile.get("business_scenarios")
            or profile.get("business_scene")
            or []
        )
        if scenes:
            parts.append("场景：" + "、".join(str(s) for s in scenes[:3])[:60])
        years = profile.get("min_years_experience")
        if isinstance(years, int) and years > 0:
            parts.append("经验：%d 年+" % years)
    if parts:
        return "；".join(parts)[:200]
    return flatten_excerpt(jd_text, 160)


def load_jobs(con: sqlite3.Connection, tenant: str) -> list[dict]:
    rows = con.execute(
        "SELECT job_id, title, company, location, job_function, jd_text, "
        "jd_profile_json FROM library_jobs WHERE tenant_id = ?",
        (tenant,),
    ).fetchall()
    jobs: list[dict] = []
    for row in rows:
        title = (row["title"] or "").strip()
        jd = (row["jd_text"] or "").strip()
        if not jd or title.lower() == "b":  # test fixture rows
            continue
        family = (row["job_function"] or "").strip() or "<空>"
        jobs.append(
            {
                "job_id": row["job_id"],
                "title": title,
                "company": (row["company"] or "").strip(),
                "location": (row["location"] or "").strip(),
                "family": family,
                "excerpt": flatten_excerpt(jd, 160),
                "requirements": requirement_summary(row["jd_profile_json"], jd),
            }
        )
    return jobs


def sample(jobs: list[dict], quotas: dict[str, int], target: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for job in jobs:
        groups.setdefault(job["family"], []).append(job)

    picked: list[dict] = []
    spare: list[dict] = []
    for family, quota in quotas.items():
        bucket = sorted(groups.get(family, []), key=lambda j: order_key(j["job_id"]))
        picked.extend(bucket[:quota])
        spare.extend(bucket[quota:])

    if len(picked) < target:  # top up deterministically if a family ran short
        spare.sort(key=lambda j: order_key(j["job_id"]))
        picked.extend(spare[: target - len(picked)])

    picked.sort(key=lambda j: (j["family"], order_key(j["job_id"])))
    return picked


def resume_titles(con: sqlite3.Connection, resume_ids: list[str]) -> dict[str, str]:
    marks = ",".join("?" for _ in resume_ids)
    rows = con.execute(
        "SELECT resume_id, title FROM master_resumes WHERE resume_id IN (" + marks + ")",
        tuple(resume_ids),
    ).fetchall()
    return {row["resume_id"]: (row["title"] or "").strip() for row in rows}


def counts_by_family(jobs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job["family"]] = counts.get(job["family"], 0) + 1
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the ADR-0065 A1 sheet")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--out", default=".scratch/ranking-a1/annotation-sheet.csv")
    parser.add_argument("--target", type=int, default=50)
    parser.add_argument("--resume-a", required=True)
    parser.add_argument("--resume-b", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    con = connect_readonly(args.db)
    try:
        jobs = load_jobs(con, args.tenant)
        titles = resume_titles(con, [args.resume_a, args.resume_b])
    finally:
        con.close()

    if len(titles) != 2:
        raise SystemExit(
            "resume id not found in tenant %s: %s" % (args.tenant, sorted(titles))
        )

    picked = sample(jobs, DEFAULT_QUOTAS, args.target)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "序号",
                "job_id",
                "标题",
                "公司",
                "城市",
                "岗位族",
                "岗位要求摘要",
                "JD摘要(前160字)",
                "简历A相关(0/1)",
                "简历B相关(0/1)",
                "备注",
            ]
        )
        for index, job in enumerate(picked, 1):
            writer.writerow(
                [
                    index,
                    job["job_id"],
                    job["title"],
                    job["company"],
                    job["location"],
                    job["family"],
                    job["requirements"],
                    job["excerpt"],
                    "",
                    "",
                    "",
                ]
            )

    meta = {
        "adr": "ADR-0065",
        "seed": SEED,
        "tenant": args.tenant,
        "sheet": out.as_posix(),
        "sheet_abs": str(out.resolve()),
        "count": len(picked),
        "source_count": len(jobs),
        "quotas": DEFAULT_QUOTAS,
        "families": counts_by_family(picked),
        "resume_a": {"id": args.resume_a, "title": titles[args.resume_a]},
        "resume_b": {"id": args.resume_b, "title": titles[args.resume_b]},
        "generated_by": "benchmarks/make_annotation_sheet.py",
    }
    (out.parent / "annotation-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print("sheet:", str(out.resolve()))
    print("count:", len(picked), "of", len(jobs), "candidates")
    print("families:", counts_by_family(picked))
    print("resume A:", args.resume_a, titles[args.resume_a])
    print("resume B:", args.resume_b, titles[args.resume_b])


if __name__ == "__main__":
    main()
