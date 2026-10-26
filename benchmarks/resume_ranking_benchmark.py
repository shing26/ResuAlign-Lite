"""ADR-0065 A2: resume x job ranking benchmark.

Modes:

  # 1) import the filled annotation sheet into the frozen label set
  python benchmarks/resume_ranking_benchmark.py --import-sheet .scratch/ranking-a1/annotation-sheet.csv

  # 2) evaluate with real embeddings (local Ollama bge-m3, 1024d)
  python benchmarks/resume_ranking_benchmark.py \
      --labels benchmarks/fixtures/resume_job_labels.json --embedder ollama

  # 3) offline pipeline check (deterministic hashing embedder, no network)
  python benchmarks/resume_ranking_benchmark.py --labels ... --embedder hashing

  # 4) metric math / RRF / hashing self check
  python benchmarks/resume_ranking_benchmark.py --selftest

Rankers: keyword (prematch, zero network), vector (embedder cosine) and RRF
fusion of both, plus a time-order baseline so a lucky ranking is visible.

Embedding source (ADR-0065 decision record 3): local Ollama first (bge-m3,
multilingual). The hashing embedder exists only for offline CI and its numbers
are never quality evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # noqa: E402  (same bootstrap as other benchmarks)

from resualign.prematch import compute_match_signals  # noqa: E402

LABELS_DEFAULT = ROOT / "benchmarks" / "fixtures" / "resume_job_labels.json"
HASH_DIM = 256
RRF_K = 60
K = 10

_ASCII = re.compile(r"[a-z0-9+#.\-]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


# --------------------------------------------------------------------------- #
# embedders
# --------------------------------------------------------------------------- #
class Embedder(Protocol):
    name: str
    model: str
    dim: int
    is_real: bool

    def embed_many(self, texts: list[str]) -> list[list[float]]: ...


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def hashed_tokens(text: str) -> list[str]:
    flat = normalize(text)
    tokens = _ASCII.findall(flat)
    for run in _CJK.findall(flat):
        tokens.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return tokens


def _l2(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class HashingEmbedder:
    """Deterministic char-ngram hashing: CI only, no semantic quality."""

    name = "hashing"
    is_real = False

    def __init__(self, dim: int = HASH_DIM) -> None:
        self.model = "hashing-%d" % dim
        self.dim = dim

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        counts = [0.0] * self.dim
        for token in hashed_tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            counts[int.from_bytes(digest, "big") % self.dim] += 1.0
        return _l2(counts)


class _EmbedOverflow(Exception):
    """The batch/text exceeded the model context; caller splits or truncates."""


class OllamaEmbedder:
    """Local Ollama /api/embed (bge-m3 by default; any embedding model works)."""

    name = "ollama"
    is_real = True

    def __init__(
        self,
        model: str = "bge-m3",
        url: str = "http://127.0.0.1:11434",
        batch: int = 16,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.url = url.rstrip("/")
        self.batch = max(1, batch)
        self.timeout = timeout
        self.dim = 0

    # Ollama enforces the model context over the whole request, so a large
    # batch can 400 with "input length exceeds the context length". Batches are
    # therefore split recursively; a single over-long text is truncated to
    # max_chars (bge-m3 sees 8192 tokens; 6k chars is a safe slice for Chinese).
    max_chars = 6000

    def __init_state(self) -> None:
        self.truncated = 0
        self.split = 0
        self.requests = 0

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.__init_state()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch):
            vectors.extend(self._embed_chunk(texts[start : start + self.batch]))
        return vectors

    def _embed_chunk(self, chunk: list[str]) -> list[list[float]]:
        if not chunk:
            return []
        try:
            return self._post(chunk)
        except _EmbedOverflow:
            if len(chunk) == 1:
                return [self._embed_single(chunk[0])]
            middle = len(chunk) // 2
            return self._embed_chunk(chunk[:middle]) + self._embed_chunk(chunk[middle:])

    def _embed_single(self, text: str, depth: int = 0) -> list[float]:
        """Embed one over-long text by recursive halving + length-weighted pooling.

        Ollama refuses a single input whose token count exceeds the model context
        (observed on 1 of 50 real JDs, 4592 Chinese chars). Splitting preserves more
        of the document than a hard truncation; only a sub-1200-char piece that
        still overflows is cut.
        """
        try:
            return self._post([text])[0]
        except _EmbedOverflow:
            if len(text) <= 1200 or depth >= 3:
                self.truncated += 1
                return self._post([text[:1000]])[0]
            self.split += 1
            middle = len(text) // 2
            left = self._embed_single(text[:middle], depth + 1)
            right = self._embed_single(text[middle:], depth + 1)
            weight_left = middle / max(1, len(text))
            pooled = [
                left[i] * weight_left + right[i] * (1.0 - weight_left)
                for i in range(len(left))
            ]
            return _l2(pooled)

    def _post(self, chunk: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model, "input": chunk}).encode("utf-8")
        request = urllib.request.Request(
            self.url + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        self.requests += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if "context length" in detail:
                raise _EmbedOverflow(detail) from exc
            raise RuntimeError("ollama embed HTTP %s: %s" % (exc.code, detail)) from exc
        batch_vectors = body.get("embeddings")
        if batch_vectors is None and body.get("embedding"):
            batch_vectors = [body["embedding"]]
        if not batch_vectors or len(batch_vectors) != len(chunk):
            raise RuntimeError(
                "ollama embed returned %s vectors for %d inputs"
                % (len(batch_vectors or []), len(chunk))
            )
        vectors: list[list[float]] = []
        for vector in batch_vectors:
            if not self.dim:
                self.dim = len(vector)
            elif len(vector) != self.dim:
                raise RuntimeError(
                    "embedding dim drift: %d vs %d" % (len(vector), self.dim)
                )
            vectors.append(_l2([float(v) for v in vector]))
        return vectors


def make_embedder(args: argparse.Namespace):
    if args.embedder == "ollama":
        return OllamaEmbedder(
            model=args.embed_model, url=args.embed_url, batch=args.embed_batch
        )
    return HashingEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dim mismatch: %d vs %d" % (len(a), len(b)))
    return sum(x * y for x, y in zip(a, b))


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def recall_at_k(ranking: list[str], relevant: set[str], k: int = K) -> float | None:
    if not relevant:
        return None
    return sum(1 for job in ranking[:k] if job in relevant) / len(relevant)


def precision_at_k(ranking: list[str], relevant: set[str], k: int = K) -> float | None:
    if not relevant:
        return None
    return sum(1 for job in ranking[:k] if job in relevant) / k


def hit_at_k(ranking: list[str], relevant: set[str], k: int = K) -> float | None:
    if not relevant:
        return None
    return 1.0 if any(job in relevant for job in ranking[:k]) else 0.0


def ndcg_at_k(ranking: list[str], relevant: set[str], k: int = K) -> float | None:
    if not relevant:
        return None
    dcg = sum(
        1.0 / math.log2(i + 2)
        for i, job in enumerate(ranking[:k])
        if job in relevant
    )
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else None


def mrr(ranking: list[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    for i, job in enumerate(ranking, 1):
        if job in relevant:
            return 1.0 / i
    return 0.0


# --------------------------------------------------------------------------- #
# rankers
# --------------------------------------------------------------------------- #
def rank_keyword(resume_text: str, jobs: dict[str, dict]) -> list[tuple[str, float]]:
    scored = []
    for job_id, job in jobs.items():
        signals = compute_match_signals(resume_text, job["jd_text"])
        score = float(signals["overlap_ratio"]) * 100.0 + len(signals["matched_skills"])
        scored.append((job_id, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def rank_vector(resume_vec: list[float], jobs: dict[str, dict]) -> list[tuple[str, float]]:
    scored = [(job_id, cosine(resume_vec, job["vec"])) for job_id, job in jobs.items()]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def rrf_fuse(
    first: list[tuple[str, float]], second: list[tuple[str, float]], k: int = RRF_K
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in (first, second):
        for position, (job_id, _) in enumerate(ranking, 1):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def rank_time_order(jobs: dict[str, dict]) -> list[tuple[str, float]]:
    scored = [(job_id, job.get("created_at") or 0.0) for job_id, job in jobs.items()]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


# --------------------------------------------------------------------------- #
# labels: import
# --------------------------------------------------------------------------- #
def import_sheet(sheet_path: Path, meta_path: Path, out_path: Path) -> None:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    resume_a = meta["resume_a"]
    resume_b = meta["resume_b"]

    items = []
    problems = []
    with sheet_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            index = (row.get("序号") or "").strip()
            job_id = (row.get("job_id") or "").strip()
            raw_a = (row.get("简历A相关(0/1)") or "").strip()
            raw_b = (row.get("简历B相关(0/1)") or "").strip()
            if not job_id:
                problems.append("row %s: missing job_id" % index)
                continue
            for label, raw in (("A", raw_a), ("B", raw_b)):
                if raw not in {"0", "1"}:
                    problems.append(
                        "row %s resume %s: expected 0/1, got %r" % (index, label, raw)
                    )
            items.append(
                {
                    "job_id": job_id,
                    "title": (row.get("标题") or "").strip(),
                    "family": (row.get("岗位族") or "").strip(),
                    "relevant": {resume_a["id"]: raw_a, resume_b["id"]: raw_b},
                }
            )

    if problems:
        raise SystemExit(
            "annotation incomplete: %d problem(s)\n- " % len(problems)
            + "\n- ".join(problems[:20])
        )
    if len(items) < 40:
        raise SystemExit("only %d labelled items; the criteria require 40-60" % len(items))

    labels = {
        "adr": "ADR-0065",
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source_sheet": str(sheet_path),
        "frozen_until": "2027-01-26",
        "resumes": {"A": resume_a, "B": resume_b},
        "items": items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(labels, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    positives = {
        key: sum(1 for item in items if item["relevant"][info["id"]] == "1")
        for key, info in labels["resumes"].items()
    }
    print("labels:", out_path)
    print("items:", len(items), "| positives:", positives,
          "| frozen_until:", labels["frozen_until"])


# --------------------------------------------------------------------------- #
# DB access (read-only)
# --------------------------------------------------------------------------- #
def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def load_jobs(con: sqlite3.Connection, tenant: str, job_ids: list[str]) -> dict[str, dict]:
    marks = ",".join("?" for _ in job_ids)
    rows = con.execute(
        "SELECT job_id, title, jd_text, created_at, job_function FROM library_jobs "
        "WHERE tenant_id = ? AND job_id IN (" + marks + ")",
        (tenant, *job_ids),
    ).fetchall()
    jobs = {}
    for row in rows:
        jd_text = (row["jd_text"] or "").strip()
        if not jd_text:
            continue
        jobs[row["job_id"]] = {
            "title": row["title"] or "",
            "family": (row["job_function"] or "").strip() or "<empty>",
            "jd_text": jd_text,
            "created_at": row["created_at"] or 0.0,
            "vec": [],
        }
    return jobs


def load_resume_text(con: sqlite3.Connection, resume_id: str) -> str:
    row = con.execute(
        "SELECT content FROM resume_versions WHERE resume_id = ? "
        "ORDER BY version DESC LIMIT 1",
        (resume_id,),
    ).fetchone()
    return (row["content"] if row else "") or ""


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def evaluate_one(
    resume_text: str, resume_vec: list[float], jobs: dict[str, dict], relevant: set[str]
) -> dict[str, dict]:
    timings: dict[str, float] = {}

    start = time.perf_counter()
    keyword = rank_keyword(resume_text, jobs)
    timings["keyword_ms"] = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    vector = rank_vector(resume_vec, jobs)
    timings["vector_ms"] = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    fused = rrf_fuse(keyword, vector)
    timings["rrf_ms"] = (time.perf_counter() - start) * 1000

    out: dict[str, dict] = {}
    for name, ranking in (
        ("time_order", rank_time_order(jobs)),
        ("keyword", keyword),
        ("vector", vector),
        ("rrf", fused),
    ):
        ids = [job_id for job_id, _ in ranking]
        out[name] = {
            "precision@10": precision_at_k(ids, relevant),
            "recall@10": recall_at_k(ids, relevant),
            "hit@10": hit_at_k(ids, relevant),
            "nDCG@10": ndcg_at_k(ids, relevant),
            "MRR": mrr(ids, relevant),
            "top10": ids[:K],
        }
    out["_timings"] = timings
    out["_relevant"] = len(relevant)
    return out


def preview_top(
    resume_key: str, ranking: list[tuple[str, float]], jobs: dict[str, dict], k: int = K
) -> None:
    print("\n[%s] top-%d preview (sanity only, not the criterion)" % (resume_key, k))
    for position, (job_id, score) in enumerate(ranking[:k], 1):
        job = jobs[job_id]
        print(
            "  %2d. %-8s %.4f  %s | %s"
            % (position, job["family"], score, job["title"][:36], job_id[:8])
        )


def run(args: argparse.Namespace) -> None:
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    job_ids = [item["job_id"] for item in labels["items"]]

    con = connect_readonly(Path(args.db))
    try:
        jobs = load_jobs(con, args.tenant, job_ids)
        resumes = {
            key: {"info": info, "text": load_resume_text(con, info["id"])}
            for key, info in labels["resumes"].items()
        }
    finally:
        con.close()

    missing = [job_id for job_id in job_ids if job_id not in jobs]
    embedder = make_embedder(args)
    print(
        "jobs: %d labelled / %d loaded / %d missing | embedder=%s model=%s"
        % (len(job_ids), len(jobs), len(missing), embedder.name, embedder.model)
    )
    if not jobs:
        raise SystemExit("no job texts loaded")

    start = time.perf_counter()
    job_vectors = embedder.embed_many([job["jd_text"] for job in jobs.values()])
    build_ms = (time.perf_counter() - start) * 1000
    for job, vector in zip(jobs.values(), job_vectors):
        job["vec"] = vector
    extra = ""
    if getattr(embedder, "requests", None):
        extra = " | requests=%d split=%d truncated=%d" % (
            embedder.requests,
            getattr(embedder, "split", 0),
            getattr(embedder, "truncated", 0),
        )
    print(
        "embedded %d jobs in %.2fs (dim=%d, %.1f ms/doc)%s"
        % (len(jobs), build_ms / 1000, embedder.dim, build_ms / max(1, len(jobs)), extra)
    )

    report = {
        "adr": "ADR-0065",
        "embedder": embedder.name,
        "model": embedder.model,
        "dim": embedder.dim,
        "is_real_embedder": embedder.is_real,
        "tenant": args.tenant,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "job_embed_ms": round(build_ms, 1),
        "resumes": {},
    }

    for key, resume in resumes.items():
        if not resume["text"]:
            print("\n[%s] resume text missing, skipped" % key)
            continue
        start = time.perf_counter()
        resume_vec = embedder.embed_many([resume["text"]])[0]
        resume_ms = (time.perf_counter() - start) * 1000

        preview_top(key, rank_vector(resume_vec, jobs), jobs)
        relevant = {
            item["job_id"]
            for item in labels["items"]
            if item["relevant"].get(resume["info"]["id"]) == "1" and item["job_id"] in jobs
        }
        metrics = evaluate_one(resume["text"], resume_vec, jobs, relevant)
        report["resumes"][key] = {
            "resume_id": resume["info"]["id"],
            "title": resume["info"]["title"],
            "resume_embed_ms": round(resume_ms, 1),
            "metrics": metrics,
        }

        print("\n== resume %s | %s ==" % (key, resume["info"]["title"]))
        if not relevant:
            print("  no positive labels -> metrics n/a (annotation not done yet)")
            continue
        print(
            "  positives %d / %d | annotated items %d"
            % (len(relevant), len(jobs), len(job_ids))
        )
        print(_markdown_table(metrics))
        keyword_precision = metrics["keyword"]["precision@10"] or 0.0
        ceiling = min(1.0, K / max(1, len(relevant)))
        print("  recall@10 ceiling at this label set: %.1f%%" % (ceiling * 100))
        for name in ("vector", "rrf"):
            value = metrics[name]["precision@10"] or 0.0
            print(
                "  %s P@10 vs keyword: %+.1f pp (recall %+.1f pp)"
                % (
                    name,
                    (value - keyword_precision) * 100,
                    ((metrics[name]["recall@10"] or 0.0)
                     - (metrics["keyword"]["recall@10"] or 0.0)) * 100,
                )
            )
        print(
            "  latency keyword %.1fms / vector %.1fms / rrf %.1fms"
            % (
                metrics["_timings"]["keyword_ms"],
                metrics["_timings"]["vector_ms"],
                metrics["_timings"]["rrf_ms"],
            )
        )

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print("\nresult json:", args.out)

    if not embedder.is_real:
        print(
            "\nNOTE: hashing embedder = pipeline check only; "
            "its numbers are NOT quality evidence."
        )


def _markdown_table(metrics: dict) -> str:
    head = "| ranker | P@10 | recall@10 | nDCG@10 | MRR |\n| --- | --- | --- | --- | --- |"
    rows = []
    for name in ("time_order", "keyword", "vector", "rrf"):
        m = metrics[name]
        rows.append(
            "| %s | %s | %s | %s | %s |"
            % (
                name,
                _fmt(m["precision@10"]),
                _fmt(m["recall@10"]),
                _fmt(m["nDCG@10"]),
                _fmt(m["MRR"]),
            )
        )
    return head + "\n" + "\n".join(rows)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else "%.3f" % value


# --------------------------------------------------------------------------- #
# self test
# --------------------------------------------------------------------------- #
def selftest() -> None:
    relevant = {"a", "b", "c"}
    ranking = ["x", "a", "c", "y", "b"]
    assert abs(recall_at_k(ranking, relevant) - 1.0) < 1e-9
    assert hit_at_k(ranking, relevant) == 1.0
    assert abs(mrr(ranking, relevant) - 0.5) < 1e-9
    dcg = 1 / math.log2(3) + 1 / math.log2(4) + 1 / math.log2(6)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert abs(ndcg_at_k(ranking, relevant) - dcg / idcg) < 1e-9
    no_hit = ["x", "y", "z"]
    assert recall_at_k(no_hit, relevant) == 0.0
    assert mrr(no_hit, relevant) == 0.0

    fused = rrf_fuse([("a", 1.0), ("b", 2.0)], [("b", 1.0), ("a", 2.0)], k=60)
    assert abs(fused[0][1] - fused[1][1]) < 1e-12
    assert [job_id for job_id, _ in fused] == ["a", "b"]

    embedder = HashingEmbedder()
    v1 = embedder.embed_many(["java backend high concurrency qps"])[0]
    v2 = embedder.embed_many(["java backend high concurrency qps"])[0]
    v3 = embedder.embed_many(["product manager prd roadmap"])[0]
    assert v1 == v2 and v1 != v3
    assert abs(sum(v * v for v in v1) - 1.0) < 1e-9
    assert cosine(v1, v2) > 0.99 and cosine(v1, v3) < 0.5

    print("selftest ok: metrics / RRF / hashing embedder")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADR-0065 ranking benchmark")
    parser.add_argument("--import-sheet", default=None)
    parser.add_argument("--meta", default=None, help="annotation-meta.json (import mode)")
    parser.add_argument("--labels", default=str(LABELS_DEFAULT))
    parser.add_argument("--db", default=str(ROOT / "data" / "jobs.db"))
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--embedder", default="hashing", choices=["hashing", "ollama"])
    parser.add_argument("--embed-model", default="bge-m3")
    parser.add_argument("--embed-url", default="http://127.0.0.1:11434")
    parser.add_argument("--embed-batch", type=int, default=16)
    parser.add_argument("--out", default=None)
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.selftest:
        selftest()
        return
    if args.import_sheet:
        sheet = Path(args.import_sheet)
        meta = Path(args.meta) if args.meta else sheet.parent / "annotation-meta.json"
        import_sheet(sheet, meta, Path(args.labels))
        return
    run(args)


if __name__ == "__main__":
    main()
