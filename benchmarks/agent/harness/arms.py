"""Protocol arms for Phase 0: the two model-facing shapes plus a scripted actor.

- `TemplateArm`: fixed system prompt + JSON contract, one JSON object per step
  (protocol SS4.1: "你只输出一个 JSON 对象，符合给定 schema，无其他文本").
- `ToolsArm`: native OpenAI `tools` / `tool_choice`, termination = a reply with
  no tool calls.
- `ScriptedArm`: replays a pre-baked action list. Used by the offline probes so
  the judge can be validated without touching any model.

All three emit the *same* normalized attempt record, so judging is arm-agnostic
(protocol SS2: 两臂裁的是同一语义事件).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from .core import Fixture, Sim, validate_call
from .judge import MAX_STEPS

TEMPLATE_SYSTEM = (
    "你只输出一个 JSON 对象，符合给定 schema，无其他文本。"
    "schema: {\"action\":\"call\",\"tool\":<注册表内工具名>,\"args\":{...}} 或 "
    "{\"action\":\"report\",\"summary\":\"...\",\"todos\":[\"...\"]} 或 "
    "{\"action\":\"stop\",\"reason\":\"...\"}。"
    "SS 输出填空题直接输出目标对象本身（不要包 action）。"
)


class ArmResult(dict):
    pass


def _vocab_call(tool, args):
    return {"action": "call", "tool": tool, "args": args}


def _norm_output_to_action(out, fx: Fixture, arm: str) -> dict | None:
    """Map one model object to a normalized action (or None if not parseable)."""
    if not isinstance(out, dict):
        return None
    a = out.get("action")
    if arm == "ss_fields":
        return {"action": "fields", "fields": out}
    if a == "call" and "tool" in out:
        return _vocab_call(out["tool"], out.get("args") or {})
    if a == "report":
        return {"action": "report", "summary": str(out.get("summary", "")),
                "todos": [str(t) for t in (out.get("todos") or [])]}
    if a == "stop":
        return {"action": "stop", "reason": str(out.get("reason", ""))}
    return None


# --------------------------------------------------------------------------


class ScriptedArm:
    """Replays a list of raw model outputs; validation + sim behave as usual.

    Each item is either a dict (a model output object) or the string "invalid"
    (forces a ValidationError so the repair counter can be probed).
    """

    name = "scripted"

    def __init__(self, fx: Fixture, script: list, arm: str = "template", finalize=None):
        self.fx = fx
        self.script = list(script)
        self.arm = arm
        # finalize(sim, q) -> {"summary"|"reason"|"todos"}: a script entry may
        # leave the terminal wording as None, meaning "the reference answer,
        # derived from what this run actually observed". Real model arms have
        # no such hook - they must produce their own text.
        self.finalize = finalize

    def run_question(self, q: dict) -> dict:
        sim = Sim(q, self.fx)
        actions: list[dict] = []
        repairs = 0
        over = False
        steps = 0
        out_final = None
        last_norm: dict | None = None
        queue = list(self.script)
        i = 0
        while i < len(queue):
            raw = queue[i]
            i += 1
            if raw == "invalid":
                repairs += 1
                if repairs > 2:
                    over = True
                    break
                continue
            if isinstance(raw, str):
                raw = {"_unparseable": raw}
                errs = ["not a JSON object"]
            else:
                errs = self._validate(q, raw)
            if errs:
                repairs += 1
                if repairs > 2:
                    over = True
                    break
                continue
            steps += 1
            if (
                isinstance(raw, dict)
                and raw.get("action") in ("report", "stop")
                and any(raw.get(k) is None for k in ("summary", "reason", "todos"))
                and self.finalize is not None
            ):
                raw = {**{k: v for k, v in raw.items() if v is not None},
                       **self.finalize(sim, q)}
            if q["kind"] == "ss" and self.arm == "ss_fields":
                out_final = raw
                actions.append({"action": "fields", "fields": raw})
                break
            act = _norm_output_to_action(raw, self.fx, "template")
            if act is None:
                repairs += 1
                if repairs > 2:
                    over = True
                    break
                continue
            actions.append(act)
            last_norm = act
            if act["action"] == "call":
                sim.deliver(act["tool"], act.get("args"))
            else:
                break
            if steps > MAX_STEPS + 2:
                break
        if q["kind"] == "ss" and out_final is None:
            for raw in queue:
                if isinstance(raw, dict) and "action" not in raw:
                    out_final = raw
                    break
            if out_final is None:
                # An SS line answered through the action channel still has to
                # expose the object the output_schema check runs against: use
                # the normalized action (post-finalize, so no None fields).
                out_final = last_norm
        return {
            "actions": actions,
            "output": out_final,
            "repairs": repairs,
            "repairs_over_cap": over,
            "timed_out": False,
            "steps": steps,
            "sim": sim,
            "raw": self.script,
        }

    def _validate(self, q: dict, raw: dict) -> list[str]:
        if not isinstance(raw, dict):
            return ["not an object"]
        if q["kind"] == "ss" and self.arm == "ss_fields":
            return []
        a = raw.get("action")
        if a == "call":
            return validate_call(self.fx.tools, raw.get("tool", ""), raw.get("args"))
        if a in ("report", "stop"):
            return []
        if q["kind"] == "ss":
            return [] if "tool" not in raw else ["bad action"]
        return ["missing action"]


# --------------------------------------------------------------------------


def decide_action(*, calls, content: str, fill_line: bool) -> tuple[str, object]:
    """What one HTTP response means for the loop — the single place that decides.

    `fill_line` = the line's answer is a target object (every SS line). SS lines
    carry **no observation script** in the sealed fixture, so a tool call there
    cannot be dispatched without the harness inventing observations: it counts as
    an invalid output (repair) and goes back into the conversation history for
    audit, but never into `actions` (the judge's SS rule demands exactly one call).

    On a scripted line (MD/BS/SB) a call is dispatched even when the arm had
    asked for `tool_choice="none"`: swallowing it would leave an assistant
    tool_calls message with no result and burn the loop's iterations in silence —
    a harness deadlock masquerading as a model failure.

    Returns ("calls", calls) | ("fill", obj) | ("invalid", calls) | ("message", content).
    """
    if calls:
        return ("invalid", calls) if fill_line else ("calls", calls)
    parsed = _parse_json_object(content)
    if isinstance(parsed, dict) and parsed:
        return "fill", parsed
    return "message", content


def _parse_json_object(text: str):
    out = _parse_json_loose(text or "")
    return out if isinstance(out, dict) else None


class HttpArm:
    def __init__(self, fx: Fixture, cell: dict, arm: str):
        self.fx = fx
        self.cell = cell
        self.arm = arm  # "tools" | "template"
        self.timeout = float(cell.get("timeout_s", 90))

    # -- transport ----------------------------------------------------------
    def _post(self, payload: dict) -> tuple[dict, float]:
        key = os.environ.get(self.cell.get("api_key_env", ""), "") if self.cell.get("api_key_env") else ""
        url = self.cell["base_url"].rstrip("/") + "/chat/completions"
        body = dict(payload)
        body.setdefault("model", self.cell["model"])
        for k in ("temperature", "disable_thinking", "thinking"):
            if k in self.cell:
                body[k] = self.cell[k]
        for k, v in (self.cell.get("extra_body") or {}).items():
            body[k] = v
        if key:
            pass  # header only, never logged
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8")), time.time() - t0

    # -- arm shapes ---------------------------------------------------------
    def _tools_payload(self, msgs: list[dict], ss_fields: bool = False) -> dict:
        tools = [
            {"type": "function",
             "function": {"name": t["name"],
                          "description": f"tier={t['tier']}",
                          "parameters": t["args_schema"]}}
            for t in self.fx.tools.values()
        ]
        # SS fill-in lines ask for a target object, not a tool call: without
        # this the model answers by calling, gets no JSON content, and the
        # attempt dies on the repair cap for a purely mechanical reason.
        choice = "none" if ss_fields else "auto"
        return {"messages": msgs, "tools": tools, "tool_choice": choice}

    def _template_payload(self, msgs: list[dict]) -> dict:
        return {"messages": msgs}

    # -- one attempt -------------------------------------------------------
    def run_question(self, q: dict, ss_fields: bool = False) -> dict:
        """One attempt.

        SS accounting (protocol SS1): "一次输出 = 一个调用", so an SS attempt gets
        at most 1 + 2 repair outputs — a model that keeps answering a fill-in line
        with tool calls must not burn 14 requests on it (that would also blow the
        SS line of SS4.7's cost estimate). MD/BS/SB get the step cap.
        """
        sim = Sim(q, self.fx)
        prompt = self.fx.visible_text(q)
        sysmsg = TEMPLATE_SYSTEM if self.arm == "template" or ss_fields else (
            "你是简历对齐工作台的编排助手。按注册表调用工具；完成时用一条不含工具调用的"
            "消息给出 {\"action\":\"report\",\"summary\":...,\"todos\":[...]} 或 "
            "{\"action\":\"stop\",\"reason\":...}。"
        )
        msgs = [{"role": "system", "content": sysmsg},
                {"role": "user", "content": prompt}]
        actions: list[dict] = []
        raws: list[dict] = []
        repairs = 0
        over = False
        timed_out = False
        steps = 0
        out_final = None
        temp_used = None
        cap = int(q.get("max_steps") or MAX_STEPS)
        outputs = 0
        ss_output_cap = 3 if q["kind"] == "ss" else None
        while steps <= cap + 2:
            if ss_output_cap is not None and outputs >= ss_output_cap:
                break
            if self.arm == "tools" and not ss_fields:
                payload = self._tools_payload(msgs)
            elif self.arm == "tools" and ss_fields:
                payload = self._tools_payload(msgs, ss_fields=True)
            else:
                payload = {"messages": msgs}
            try:
                resp, secs = self._post(payload)
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                raws.append({"error": f"http_{e.code}", "body": body, "seconds": secs if False else None})
                if e.code in (408, 429, 500, 502, 503, 504) and repairs < 2:
                    repairs += 1
                    continue
                timed_out = True
                break
            except Exception as e:  # timeout / connection reset
                raws.append({"error": type(e).__name__, "detail": str(e)[:200]})
                timed_out = True
                break
            if resp.get("temperature") is not None:
                temp_used = resp.get("temperature")
            choice = ((resp.get("choices") or [{}])[0]).get("message", {})
            outputs += 1
            raws.append({"content": choice.get("content"), "tool_calls": choice.get("tool_calls")})
            content = choice.get("content") or ""
            mode, payload = decide_action(
                calls=choice.get("tool_calls") or [], content=content,
                fill_line=ss_fields)
            if mode == "invalid":
                # A fill-in line answered by calling: no observation script
                # exists for such a line, so there is nothing to dispatch.
                # Recorded as `steps` (protocol SS1 counts calls, not requests),
                # never as actions - the judge's SS rule asks for exactly one.
                repairs += 1
                steps += len(payload)
                if repairs > 2:
                    over = True
                    break
                msgs.append({"role": "assistant", "content": content or None,
                             "tool_calls": payload})
                msgs.append({"role": "user", "content":
                             "这行题要求直接输出目标 JSON 对象本身，不要调用工具。"})
                continue
            if mode == "calls":
                steps += len(payload)
                msgs.append({"role": "assistant", "content": content or None,
                             "tool_calls": payload})
                for c in payload:
                    fn = (c.get("function") or {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {"_unparsed_arguments": fn.get("arguments")}
                    act = _vocab_call(name, args)
                    actions.append(act)
                    obs = sim.deliver(name, args)
                    msgs.append({"role": "tool", "tool_call_id": c.get("id", ""),
                                 "content": json.dumps(obs, ensure_ascii=False)})
                continue
            out = payload if mode == "fill" else _parse_json_loose(content)
            if out is None:
                repairs += 1
                if repairs > 2:
                    over = True
                    break
                msgs.append({"role": "assistant", "content": content})
                msgs.append({"role": "user", "content": "输出不符合契约：只输出一个 JSON 对象。"})
                continue
            steps += 1
            if ss_fields or (q["kind"] == "ss" and "output_schema" in q and "tool" not in (out or {})):
                out_final = out
                actions.append({"action": "fields", "fields": out})
                break
            act = _norm_output_to_action(out, self.fx, "template")
            if act is None:
                repairs += 1
                if repairs > 2:
                    over = True
                    break
                continue
            actions.append(act)
            if act["action"] == "call":
                obs = sim.deliver(act["tool"], act.get("args"))
                msgs.append({"role": "assistant", "content": content})
                if self.arm == "tools":
                    msgs.append({"role": "tool", "tool_call_id": "manual",
                                 "content": json.dumps(obs, ensure_ascii=False)})
                else:
                    msgs.append({"role": "user", "content": json.dumps(obs, ensure_ascii=False)})
                continue
            break
        return {
            "actions": actions,
            "output": out_final,
            "repairs": repairs,
            "repairs_over_cap": over,
            "timed_out": timed_out,
            "steps": steps,
            "sim": sim,
            "raw": raws,
            "latency_s": None,
            # null when the node does not echo it - README says to check by hand
            "temperature_requested": self.cell.get("temperature"),
            "temperature_used": temp_used,
        }


def _parse_json_loose(text: str):
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    start = t.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start : i + 1])
                    except Exception:
                        return None
    return None
