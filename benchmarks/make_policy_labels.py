"""ADR-0065: build policy labels from the author's declared apply policy.

Policy (author, 2026-10-27):
  target families: 后端 / 算法 / 数据 / 测试(开发)
  excluded families: 运营 / 销售 / 外包
  internships count as applicable
  (everything outside the target families is NOT applied to => label 0)

Fully deterministic from library_jobs.job_function (+ title/company for 外包),
so the label set is reproducible and, crucially, independent of both the keyword
ranker and the embedding ranker (no shared signal with either).

Two output sets:
  --full      all labelled jobs (positives 198 / negatives 35 => 85% positive pool)
  --balanced  all negatives + a deterministic sample of positives (default 35+35),
              because an 85%-positive pool makes P@10 saturate for every ranker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / ".scratch" / "ranking-a1"
SEED = "adr-0065-policy-v1"
TARGET_FAMILIES = {"后端", "算法", "数据", "测试"}
NON_TARGET_FAMILIES = {"产品", "运营", "前端", "运维", "架构", "其他"}
OUTSOURCE_RE = re.compile(r"外包|驻场|派遣|人力服务|劳务")


def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect("file:" + db.resolve().as_posix() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT job_id, title, company, job_function FROM library_jobs "
        "WHERE tenant_id = 'local' AND jd_text IS NOT NULL AND trim(jd_text) <> ''"
    ).fetchall()
    jobs = []
    for row in rows:
        family = (row["job_function"] or "").strip()
        haystack = (row["title"] or "") + " " + (row["company"] or "")
        outsourced = bool(OUTSOURCE_RE.search(haystack))
        if family in TARGET_FAMILIES and not outsourced:
            label = 1
        elif family in NON_TARGET_FAMILIES or outsourced:
            label = 0
        else:
            continue  # unclassified: cannot infer from policy
        jobs.append(
            {
                "job_id": row["job_id"],
                "title": row["title"] or "",
                "family": family,
                "outsourced": outsourced,
                "label": label,
            }
        )
    return jobs


def order_key(job_id: str) -> str:
    return hashlib.sha256((SEED + "|" + job_id).encode("utf-8")).hexdigest()


def build(jobs: list[dict], resumes: dict, label_kind: str, policy: str) -> dict:
    items = [
        {
            "job_id": job["job_id"],
            "title": job["title"],
            "family": job["family"],
            "relevant": {
                resumes["A"]["id"]: str(job["label"]),
                resumes["B"]["id"]: str(job["label"]),
            },
            "label_source": "policy",
        }
        for job in jobs
    ]
    return {
        "adr": "ADR-0065",
        "label_kind": label_kind,
        "created_at": "2026-10-27",
        "policy": policy,
        "seed": SEED,
        "limitations": [
            "policy-level labels (family + outsource rule), not nuanced willingness",
            "resume-independent: both resumes share the same labels",
            "unclassified jobs (no job_function) are excluded, not guessed",
            "tests 'does the ranking comply with the declared policy'",
        ],
        "resumes": resumes,
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="build ADR-0065 policy labels")
    parser.add_argument("--db", default=str(ROOT / "data" / "jobs.db"))
    parser.add_argument("--positives", type=int, default=35)
    args = parser.parse_args()

    zeros = json.loads((OUT_DIR / "labels-zeros.json").read_text(encoding="utf-8"))
    resumes = zeros["resumes"]
    policy = (
        "只投 后端/算法/数据/测试开发；运营/销售/外包不投；实习也投。"
        "（2026-10-27 作者口述）"
    )

    con = connect(Path(args.db))
    try:
        jobs = load(con)
    finally:
        con.close()

    positives = [job for job in jobs if job["label"] == 1]
    negatives = [job for job in jobs if job["label"] == 0]

    full = build(jobs, resumes, "policy_full", policy)
    (OUT_DIR / "labels-policy-full.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    sampled_positives = sorted(positives, key=lambda job: order_key(job["job_id"]))[
        : args.positives
    ]
    balanced_jobs = negatives + sampled_positives
    balanced = build(balanced_jobs, resumes, "policy_balanced", policy)
    balanced["balanced_note"] = (
        "all negatives (n=%d) + %d deterministic positives; P@10 random baseline = 50%%"
        % (len(negatives), len(sampled_positives))
    )
    (OUT_DIR / "labels-policy-balanced.json").write_text(
        json.dumps(balanced, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print("labelled jobs:", len(jobs), "| pos:", len(positives), "| neg:", len(negatives))
    print("full ->", OUT_DIR / "labels-policy-full.json")
    print(
        "balanced ->",
        OUT_DIR / "labels-policy-balanced.json",
        "| pos:", len(sampled_positives), "| neg:", len(negatives),
    )


if __name__ == "__main__":
    main()
