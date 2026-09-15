---
name: true-tailor
description: Tailor a resume to a job description with every rewrite verifiably traced to the candidate's own source text. The fabrication gate is code, not a promise — gate.py deterministically blocks suggestions whose provenance cannot be located in the resume and whose numbers or named tools/entities have no source in it. Use when the user asks to align/tailor/audit a resume against a specific JD, or wants honest rewrite suggestions.
---

# True Tailor — resume alignment you can sign

You rewrite a resume toward one job description. You do not invent.
Everything you produce is submitted to a deterministic gate before the
user sees it. Follow the four steps in order, then re-evaluate.

## Iron rules (non-negotiable)

1. **Never invent.** You may rephrase, reorder, and re-emphasize facts
   that exist in the master resume. New numbers, employers, tools,
   projects, or outcomes are forbidden. The gate catches the ones it can
   prove — any digit not present in the source text, and any named
   non-Chinese tool or entity absent from it — plus any quote that cannot
   be located. It cannot read your intent, and it does not parse Chinese
   word by word. So the real rule is: **every claim you write must be
   locatable in the resume, and you must cite the line.**
2. **The gate decides, not you.** Step 3 is mandatory on every round.
   A diff that never passed `gate.py` must never be presented as a
   suggestion, quoted as accepted, or applied to any draft.
3. **Paste, don't paraphrase.** The `GATE:` summary line goes into your
   reply verbatim. You are forbidden from restating its numbers.
4. **Blocked ≠ deleted.** Show every blocked diff in a short
   "needs review" list with the gate's reason. Silent dropping is a
   contract violation.
5. **Thin is honest, padding is not.** A round with few usable diffs is a
   pass if the gaps are real. Never add, soften, or invent a diff to make
   the count look better. Report a weak round as weak.

## Step 0 — Inputs

Ask for, then save to the working directory:
- `resume.md` — the master resume (paste; any plain-text format)
- `jd.txt` — one job description (paste the text; no links)

If either is missing, stop and ask. One resume, one JD per session.

`gate.py` sits next to this SKILL.md, not in your working directory:

| Host | Gate path |
|---|---|
| Claude Code | `~/.claude/skills/true-tailor/gate.py` |
| Codex | `~/.codex/skills/true-tailor/gate.py` |

Resolve it to an absolute path once and reuse it. Never copy the gate
into the user's project, and never rewrite it (see Environment).

## Step 1 — Gap analysis

Compare resume against JD. Write `gap.json`:

```json
{
  "missing_keywords": ["terms the JD requires that the resume proves but never states"],
  "misaligned_emphasis": ["facts present but framed for the wrong audience"],
  "strength_matches": ["direct hits to keep"],
  "business_scenarios": ["contexts the JD names, e.g. 高并发"],
  "jd_context": "one-line summary of what this employer is buying"
}
```

Hard line: `missing_keywords` may only contain skills the resume
**evidences somewhere**. A JD requirement with no evidence in the resume
is a genuine gap — record it in your reply as "cannot honestly tailor",
never as a rewrite target.

Keep the read cheap: walk the resume once, quote nothing longer than one
line, and keep `gap.json` under roughly 15 entries. On slower or smaller
models, re-pasting the whole resume into every step is what makes the gap
analysis stall; cite short anchors instead.

## Step 2 — Tailored diffs

Produce suggestions as `diffs.json`, highest impact first. Tie every diff
to one named `gap.json` item and say which in `reason` — that mapping is
the difference between a tailoring plan and a rewrite of whatever happened
to be at the top of the file.

Output floor: if `gap.json` names 3 or more addressable gaps but you
drafted fewer than 3 diffs, work the gap list again once, item by item,
before writing the file. One retry, no more. If gaps genuinely cannot be
closed without inventing, stop drafting and go to Step 3 with what you
have — the gate and your report both expect an honest short round.

```json
[{
  "diff_id": "r1d1",
  "type": "modify | add | remove",
  "section": "exact section heading from the resume",
  "original": "VERBATIM resume substring (add: the supporting sentence your addition rests on)",
  "proposed": "the rewrite, <=250 chars",
  "provenance": "VERBATIM resume substring this suggestion is anchored to",
  "reason": "why this helps against this JD",
  "confidence": "high | medium | low"
}]
```

`original` and `provenance` must be copy-paste substrings, not
paraphrases — the gate matches them character by character (with a
tolerance for whitespace and small misquotes, which it then corrects to
the real source line).

Keep each `proposed` under 250 characters. That is a writing discipline
this skill asks of you, not something the gate enforces.

## Step 3 — Run the gate (mandatory)

```bash
python <gate_path> --resume resume.md --diffs diffs.json --allowlist gap.json \
  --log tailoring.jsonl --round <N> --trigger <T>
```

Pass `--round` and `--trigger` explicitly; never rely on the defaults.
Round 1 is `--round 1 --trigger manual`. Every round after that is
`--round N --trigger eval:round<N-1>`, and the gate appends a `chain`
block to each `tailoring.jsonl` line recording whether that round really
follows the previous logged one. A run whose `cites_prev` is false is not
evidence of iteration, whatever the prose around it claims.

`--allowlist gap.json` lets JD vocabulary through the content check —
that is the only legitimate source of "new" terms.

Then, in your reply:
- paste the `GATE:` line verbatim;
- present only `usable` diffs as suggestions (quote the gate-corrected
  `original` when the report marks a diff as salvaged);
- list `blocked` diffs with their reasons under "needs review".

**Zero usable diffs is a result to report, not a status to hide.** Name
which of the two shapes you are in, because they need different next
steps and the data alone cannot tell them apart:

- `gap.json` had addressable items and the gate left nothing usable →
  this round **failed on quality**. Say so, point at the block reasons,
  and offer a re-run (stronger model, or a fresh Step 2 over the same
  gap list).
- `gap.json` had no addressable item at all → report **"no gap worth a
  rewrite for this pair"**, never "already aligned", and offer a
  different model or a different JD before the user concludes the resume
  needs nothing.

A green pipeline with empty output is a failure to report, not a success.

## Step 4 — Re-evaluate, then propose the next round

After the user accepts/rejects diffs (or asks for round 2+):

1. Apply accepted diffs to a candidate copy `resume.r<N>.md`.
2. Re-score the candidate against `jd.txt`: which `gap.json` items are
   closed, which remain, what evidence is still missing. Apply the gate
   to the candidate, not the master — the `resume-sha256` in the summary
   line is how a later reader tells the two runs apart.
3. Append your evaluation as a short block titled `EVAL round <N>:` in
   your reply.
4. If material gaps remain, **propose** a next round and record why:
   the next round's `--trigger` must be `eval:round<N>` citing a
   specific finding of this evaluation. Never start a new round without
   the user's go-ahead, and every diff in that round must cite the EVAL
   finding it answers.

## Round discipline (the audit trail)

`tailoring.jsonl` is append-only evidence: one line per gate run with
round number, trigger, counts, the hashed resume, and the `chain` block.
Rounds must chain — round N+1's trigger cites round N's evaluation. That
chain is what makes "we iteratively improved this resume" a verifiable
claim instead of a vibe. If the user wants proof, show them this file and
the `GATE:` lines, not your summary of them.

## What the gate enforces, and what it does not

Enforced by code, on every diff, every round:
- `provenance` must be locatable in the resume (verbatim, or whitespace /
  small-misquote tolerant, in which case the diff is marked `salvaged` and
  the quote is corrected to the real source line);
- an `add` diff must carry the supporting sentence it rests on;
- digits in `proposed` must exist in the resume (or the allowlist);
- named non-Chinese tools/entities in `proposed` must exist in the resume
  (or the allowlist);
- a `modify`/`remove` whose proposed text equals its original is blocked
  as `noop`.

Not enforced, by design:
- Chinese phrases, which have no word boundary to check — a coined
  Chinese buzzword passes the content check and is stopped only by the
  verbatim-provenance requirement;
- whether a rewrite is worth making, on-topic, or well written;
- that the resume is a good match for the JD. Matching is Step 1 and
  Step 4 judgment, and the gate will never pretend otherwise.

## Environment

- `gate.py` is pure Python standard library. Any `python3` runs it; no
  install, no network, no API keys. The model doing Steps 1-4 is your
  host agent's model — expect weak local models (small Ollama builds)
  to produce thin output; the gate will honestly report it, and Step 3
  tells you how to say so.
- Never edit gate.py to make a diff pass. Editing the gate is the same
  sin as fabricating the diff. If a user asks you to, decline and explain
  that the gate's value is precisely that they cannot tune it away.
- To prove the gate to a skeptical user, run the repo's `selftest.py`:
  it replays the ten golden scenarios (fabrication, salvage, noop, add,
  allowlist) through the same code path and prints the `GATE:` line a
  real run would print.
