"""Phase 0 harness core: fixture loading, prompt assembly, schema validation, world sim.

Stdlib only. No product imports (protocol SS4.7: Phase 0 runs with zero product code).
The judging contract lives in benchmarks/agent/PHASE0_PROTOCOL.md (+ the v1.1
appendix); this module implements exactly what those texts make mechanical, and
reports every assertion it cannot judge as `unjudged` instead of guessing.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from collections import OrderedDict
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
FIXTURE_PATH = AGENT_DIR / "fixtures" / "phase0_q4_v1.jsonl"
PROTOCOL_PATH = AGENT_DIR / "PHASE0_PROTOCOL.md"

QUESTION_KINDS = ("ss", "md", "bs", "sb")


# --------------------------------------------------------------------------
# fixture loading (append-only overlay: later line with same (kind,id) wins)
# --------------------------------------------------------------------------


def _load_lines(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in raw if l.strip()]


def load_fixture(path: Path | None = None) -> "Fixture":
    return Fixture(_load_lines(path or FIXTURE_PATH))


class Fixture:
    def __init__(self, lines: list[dict]):
        self.raw_lines = lines
        eff: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self.overridden: list[str] = []
        for ln in lines:
            kind = ln.get("kind")
            if kind == "_meta":
                key = ("_meta", ln.get("id", "_meta"))
            elif kind == "tool":
                key = ("tool", ln["name"])
            elif kind == "world":
                key = ("world", ln["id"])
            else:
                key = (kind, ln["id"])
            if key in eff:
                self.overridden.append(key[1])
            eff[key] = ln
        self.effective = eff
        self.meta = eff[("_meta", "_meta")] if ("_meta", "_meta") in eff else next(
            l for l in lines if l.get("kind") == "_meta"
        )
        # real meta key carries the fixture id, not "_meta"
        for (k, v), ln in eff.items():
            if k == "_meta":
                self.meta = ln
        self.tools = OrderedDict(
            (name, ln) for (kind, name), ln in eff.items() if kind == "tool"
        )
        self.world = next((ln for (k, _), ln in eff.items() if k == "world"), None)
        self.questions = [
            ln
            for (kind, _), ln in eff.items()
            if kind in QUESTION_KINDS
        ]
        order = {k: i for i, k in enumerate(QUESTION_KINDS)}
        self.questions.sort(key=lambda q: (order[q["kind"]], q["id"]))
        # v1.1 is identified by the prompt contract existing at all: the
        # sealed meta row may carry it as a sibling key (as the input pack
        # writes it) or nested inside judgment_contract. Deriving this
        # wrongly silently switches the identity rules off.
        self.version = "v1.1" if self.prompt_contract or (
            "prompt_contract" in self.judgment_contract
        ) else "v1"

    # -- contract accessors -------------------------------------------------
    @property
    def judgment_contract(self) -> dict:
        return self.meta.get("judgment_contract", {}) or {}

    @property
    def prompt_contract(self) -> dict:
        return (
            self.meta.get("prompt_contract")
            or self.judgment_contract.get("prompt_contract")
            or {}
        )

    @property
    def vocab(self) -> dict:
        return self.meta.get("vocab", {}) or {}

    @property
    def anchor_today(self) -> str:
        return self.meta.get("anchor_today", "")

    @property
    def selector_identity(self) -> bool:
        """v1.1: multiset elements carry script-key identity; v1: (tool,count) only."""
        return self.version == "v1.1"

    @property
    def unmatched_args_rule(self) -> bool:
        return "unmatched_args" in self.judgment_contract

    def question(self, qid: str) -> dict:
        for kind in QUESTION_KINDS:
            ln = self.effective.get((kind, qid))
            if ln:
                return ln
        raise KeyError(qid)

    # -- prompt assembly (prompt_contract.never is a hard exclusion) --------
    def registry_view(self) -> list[dict]:
        return [
            {"name": t["name"], "tier": t["tier"], "args_schema": t["args_schema"]}
            for t in self.tools.values()
        ]

    def visible_text(self, q: dict) -> str:
        """Text the model is allowed to see, for one question."""
        parts: list[str] = []
        body = q.get("instruction") or q.get("input") or ""
        if body:
            parts.append(body)
        st = q.get("state") or q.get("state_visible")
        if st is not None:
            parts.append(
                st if isinstance(st, str) else json.dumps(st, ensure_ascii=False)
            )
        if self.anchor_today:
            parts.append(f"今天={self.anchor_today}")
        parts.append("工具注册表: " + json.dumps(self.registry_view(), ensure_ascii=False))
        parts.append("动作词表: " + json.dumps(self.vocab, ensure_ascii=False))
        return "\n".join(parts)

    def audit_prompt_leakage(self) -> list[dict]:
        """fact_hiding / prompt_contract audit (v1.1 only; never a model failure)."""
        findings: list[dict] = []
        never = self.prompt_contract.get("never", [])
        for q in self.questions:
            vis = self.visible_text(q)
            # hidden-field text must not leak into the prompt
            for fld in (
                "script",
                "expected",
                "expected_multiset",
                "conclusion_rules",
                "forbidden",
                "violation",
                "world_override",
                "note",
            ):
                if fld in q and isinstance(q[fld], str):
                    frag = q[fld].strip()
                    if len(frag) >= 8 and frag in vis:
                        findings.append({"id": q["id"], "leak": f"field:{fld}"})
        return findings


# --------------------------------------------------------------------------
# schema validation for the two shapes the fixture uses
# --------------------------------------------------------------------------

_TYPE_WORDS = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _check_jsonschema(instance, schema, path="$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    types = t if isinstance(t, list) else [t] if t else []
    if types:
        ok = False
        for tt in types:
            if tt == "null" and instance is None:
                ok = True
            py = _TYPE_WORDS.get(tt)
            if py and isinstance(instance, py) and not (tt in ("integer", "number") and isinstance(instance, bool)):
                ok = True
        if not ok:
            errs.append(f"{path}: {type(instance).__name__} not in {types}")
            return errs
    if isinstance(instance, dict):
        props = schema.get("properties", {}) or {}
        for k, v in instance.items():
            if k not in props:
                if schema.get("additionalProperties", True) is False:
                    errs.append(f"{path}: unknown property {k}")
                continue
            errs += _check_jsonschema(v, props[k], f"{path}.{k}")
        for req in schema.get("required", []) or []:
            if req not in instance:
                errs.append(f"{path}: missing required {req}")
    if isinstance(instance, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(instance):
            errs += _check_jsonschema(v, schema["items"], f"{path}[{i}]")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in enum")
    return errs


def _check_dsl(instance, spec, path="$") -> list[str]:
    """Validate against the fixture's compact output_schema DSL.

    spec forms: "string" | "integer" | "boolean" | "integer|null" |
    "enum(a,b)" | [subspec] | {field: subspec}
    """
    errs: list[str] = []
    if isinstance(spec, str):
        words = spec.split("|")
        if any(w.startswith("enum(") for w in words):
            vals: list[object] = []
            for w in words:
                m = re.fullmatch(r"enum\((.*)\)", w)
                if m:
                    vals += [v.strip() for v in m.group(1).split(",")]
                else:
                    words[words.index(w)] = w  # non-enum alternative handled below
            if instance not in vals:
                # allow plain-type alternatives, e.g. "enum(..)|null"
                if not _dsl_type_ok(instance, [w for w in words if not w.startswith("enum(")]):
                    errs.append(f"{path}: {instance!r} not in {spec}")
            return errs
        if not _dsl_type_ok(instance, words):
            errs.append(f"{path}: {instance!r} violates {spec!r}")
        return errs
    if isinstance(spec, list):
        if not isinstance(instance, list):
            return [f"{path}: expected array"]
        for i, v in enumerate(instance):
            errs += _check_dsl(v, spec[0], f"{path}[{i}]")
        return errs
    if isinstance(spec, dict):
        if not isinstance(instance, dict):
            return [f"{path}: expected object"]
        for k, sub in spec.items():
            if k not in instance:
                errs.append(f"{path}: missing {k}")
            else:
                errs += _check_dsl(instance[k], sub, f"{path}.{k}")
        extra = set(instance) - set(spec)
        if extra:
            errs.append(f"{path}: unexpected keys {sorted(extra)}")
        return errs
    return errs


def _dsl_type_ok(instance, words: list[str]) -> bool:
    for w in words:
        w = w.strip()
        if w == "null" and instance is None:
            return True
        py = _TYPE_WORDS.get(w)
        if py and isinstance(instance, py) and not (w == "integer" and isinstance(instance, bool)):
            return True
    return False


def validate_call(tools: dict, name: str, args) -> list[str]:
    if name not in tools:
        return [f"unknown tool {name!r} (not in registry)"]
    schema = tools[name].get("args_schema") or {}
    if not isinstance(args, dict):
        return [f"{name}.args must be object, got {type(args).__name__}"]
    errs = _check_jsonschema(args, schema, f"{name}.args")
    # required-by-convention: any property the model omits is allowed (schemas
    # here use additionalProperties:false + optional fields), but a tool whose
    # only property is the id must receive it, else the call cannot be judged.
    props = (schema.get("properties") or {})
    if props and not args:
        errs.append(f"{name}.args empty; registry declares {sorted(props)}")
    return errs


def validate_output(instance, output_schema: dict) -> list[str]:
    return _check_dsl(instance, output_schema)


# --------------------------------------------------------------------------
# script-key selectors
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def split_key(key: str) -> tuple[str, str | None]:
    if ":" in key:
        tool, sel = key.split(":", 1)
        return tool, sel
    return key, None


def _date_near(a: str, b: str, days: int = 1) -> bool:
    try:
        da = _dt.date.fromisoformat(a)
        db = _dt.date.fromisoformat(b)
    except Exception:
        return False
    return abs((da - db).days) <= days


def _arg_values(args) -> list[str]:
    out: list[str] = []
    if isinstance(args, dict):
        for v in args.values():
            if isinstance(v, list):
                out += [str(x) for x in v]
            elif v is not None:
                out.append(str(v))
    return out


def selector_matches(key: str, args: dict, ctx: dict) -> bool:
    """Does this call hit script key? v1.1 SS6.1 rules (with the three tolerances)."""
    tool, sel = split_key(key)
    ctool = ctx.get("tool")
    if ctool != tool:
        return False
    if sel is None:
        return True
    vals = _arg_values(args)
    joined = " ".join(vals)
    tokens = sel.split("+")
    for tok in tokens:
        if tok.endswith("@week"):
            # script key means "the previous natural week": accept any ISO date
            # that points into the anchor's previous week window (SS6.1 rule 4
            # tolerance is +/-1 day around that intent).
            stem = tok[: -len("@week")]
            if stem not in (args or {}):
                return False
            d = str((args or {}).get(stem, ""))
            if not _DATE_RE.fullmatch(d):
                return False
            return _in_prev_week_window(d, ctx.get("anchor_today"))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tok):
            if not any(_date_near(v, tok, 1) for v in vals if _DATE_RE.fullmatch(v or "")):
                return False
            continue
        if tok.startswith("JD-") or tok.startswith("JD_"):
            # ingest_jd: tail tag present, or >=12 chars of that JD's body
            if tok in joined:
                continue
            body = (ctx.get("jd_bodies") or {}).get(tok, "")
            norm = re.sub(r"\s+", "", joined)
            if body and re.sub(r"\s+", "", body)[:12] in norm:
                continue
            return False
        if any(tok == v or tok in v for v in vals):
            continue
        return False
    return True


def _in_prev_week_window(d: str, anchor: str | None) -> bool:
    try:
        dd = _dt.date.fromisoformat(d)
        a = _dt.date.fromisoformat(anchor) if anchor else _dt.date.today()
    except Exception:
        return False
    monday_this = a - _dt.timedelta(days=a.weekday())
    prev_mon = monday_this - _dt.timedelta(days=7)
    return (prev_mon - _dt.timedelta(days=1)) <= dd <= (prev_mon + _dt.timedelta(days=8))


# --------------------------------------------------------------------------
# world sim: delivers scripted observations, tracks hits
# --------------------------------------------------------------------------


class Sim:
    """Scripted observation server for one attempt.

    Delivery never depends on whether the model did the right thing: the script
    is pre-sealed (protocol SS4.1). A call that hits no key gets an error
    observation and is recorded for the judge.
    """

    def __init__(self, question: dict, fixture: Fixture):
        self.q = question
        self.fx = fixture
        self.script: dict = dict(question.get("script") or {})
        self.keys = list(self.script)
        self.cursor = {k: 0 for k in self.keys}
        self.calls: list[dict] = []          # {tool,args,key|None,obs}
        self.hits: list[str] = []           # script keys actually hit
        self.errors: list[dict] = []        # schema/unknown-tool errors
        self.approval_at: list[int] = []    # call index returning approval_required
        self.observations: list[object] = []
        self.ctx = self._build_ctx()

    def _build_ctx(self) -> dict:
        body = self.q.get("instruction") or self.q.get("input") or ""
        jd_bodies: dict[str, str] = {}
        for m in re.finditer(r"(JD-[A-Z])（(.*?)）", body):
            jd_bodies[m.group(1)] = m.group(2)
        anchor = self.fx.anchor_today
        week = None
        try:
            d = _dt.date.fromisoformat(anchor)
            week = (d - _dt.timedelta(days=d.weekday())).isoformat()
        except Exception:
            pass
        return {"tool": None, "anchor_week": week, "anchor_today": anchor,
                "jd_bodies": jd_bodies}

    # -- helpers ------------------------------------------------------------
    def state_values(self) -> set[str]:
        """Values declared in the visible state (SS6.1 exception 2 / unmatched rule)."""
        out: set[str] = set()
        st = self.q.get("state") or {}
        stack = [st]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                stack += list(cur.values())
            elif isinstance(cur, list):
                stack += cur
            elif isinstance(cur, str):
                out.update(re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{1,}|job_\w+|mr_\w+|b\d+", cur))
                out.update(re.findall(r"\d+", cur))
        text = self.q.get("instruction") or self.q.get("input") or ""
        out.update(re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{1,}", text))
        out.update(re.findall(r"\d+", text))
        return out

    def key_for_call(self, tool: str, args) -> str | None:
        self.ctx["tool"] = tool
        for k in self.keys:
            ktool, _ = split_key(k)
            if ktool != tool:
                continue
            if self.cursor[k] >= len(self.script[k]) and self.fx.selector_identity:
                pass  # exhausted keys may still be re-hit (repeat last observation)
            if selector_matches(k, args if isinstance(args, dict) else {}, self.ctx):
                return k
        return None

    def deliver(self, tool: str, args) -> dict:
        """Return the observation for one call action."""
        errs = validate_call(self.fx.tools, tool, args)
        rec = {"tool": tool, "args": args, "key": None, "obs": None, "errors": errs}
        if errs:
            rec["obs"] = {"error": "schema_invalid", "detail": errs}
            self.errors.append({"tool": tool, "args": args, "errors": errs})
            self.calls.append(rec)
            return rec["obs"]
        key = self.key_for_call(tool, args)
        if key is None:
            rec["obs"] = {"error": "no_script_key", "tool": tool}
            self.calls.append(rec)
            return rec["obs"]
        rec["key"] = key
        seq = self.script[key]
        i = self.cursor[key]
        obs = seq[i] if i < len(seq) else seq[-1]
        self.cursor[key] = i + 1
        self.hits.append(key)
        self.calls.append(rec)
        rec["obs"] = obs
        self.observations.append(obs)
        if isinstance(obs, dict) and obs.get("approval_required"):
            self.approval_at.append(len(self.calls) - 1)
        return obs

    # -- facts derived for judging -----------------------------------------
    def numbers_from_observations(self) -> set[str]:
        nums: set[str] = set()

        def walk(v):
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)):
                nums.add(str(int(v)) if float(v).is_integer() else str(v))
            elif isinstance(v, str):
                nums.update(re.findall(r"\d+", v))
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)

        for o in self.observations:
            walk(o)
        return nums

    def strings_from_observations(self) -> set[str]:
        out: set[str] = set()

        def walk(v):
            if isinstance(v, str):
                out.add(v)
                out.update(re.findall(r"\w[\w.+\-]{1,}", v))
            elif isinstance(v, dict):
                for k, x in v.items():
                    out.add(str(k))
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out.add(str(v))

        for o in self.observations:
            walk(o)
        return out

    def score_pairs(self) -> dict[str, set[str]]:
        """job_id -> scores returned for that job (MD-01 pairing rule)."""
        pairs: dict[str, set[str]] = {}
        for rec in self.calls:
            if not rec["key"]:
                continue
            _, sel = split_key(rec["key"])
            obs = rec["obs"]
            if isinstance(obs, dict):
                for k, v in obs.items():
                    if k in ("score", "weighted") and isinstance(v, (int, float)):
                        if sel:
                            pairs.setdefault(sel, set()).add(str(int(v)))
        return pairs

    def done_keys(self) -> list[str]:
        return [k for k in self.hits if self._obs_ok(self._obs_for_key(k)) and k not in self._error_keys()]

    def _obs_for_key(self, key):
        for rec in reversed(self.calls):
            if rec["key"] == key:
                return rec["obs"]
        return None

    def _obs_ok(self, obs) -> bool:
        return not (isinstance(obs, dict) and (obs.get("error") or obs.get("ok") is False or str(obs.get("status", "")).startswith("4")))

    def _error_keys(self) -> set[str]:
        return {
            rec["key"]
            for rec in self.calls
            if rec["key"] and not self._obs_ok(rec["obs"])
        }

    def job_hits(self, tool_prefix: str = "align_job") -> list[str]:
        out = []
        for rec in self.calls:
            if rec["key"] and rec["key"].startswith(tool_prefix + ":"):
                out.append(split_key(rec["key"])[1])
        return out


# --------------------------------------------------------------------------
# hashing / provenance
# --------------------------------------------------------------------------


def git_blob_hash(relpath: str, rev: str = "HEAD") -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", f"{rev}:{relpath}"],
            cwd=str(AGENT_DIR.parent.parent),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unavailable"


def git_show_text(relpath: str, rev: str) -> str:
    """Verbatim blob of `rev:relpath`. Once the seal moves append-only, the
    working tree no longer holds older texts — sealed baselines live in git."""
    import subprocess

    out = subprocess.run(
        ["git", "show", f"{rev}:{relpath}"],
        cwd=str(AGENT_DIR.parent.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_overlay_file(path: Path) -> list[dict]:
    """Load extra fixture lines from a jsonl file (used to build v1.1 locally)."""
    return _load_lines(path)
