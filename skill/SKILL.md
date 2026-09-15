---
name: true-tailor
description: Tailor a resume to a job description with every rewrite verifiably traced to the candidate's own source text. The fabrication gate is code, not a promise — gate.py deterministically blocks any suggestion whose provenance or content cannot be found in the original resume. Use when the user asks to align/tailor/audit a resume against a specific JD, or wants honest rewrite suggestions.
---

# True Tailor — resume alignment you can sign

You rewrite a resume toward one job description. You do not invent.
Everything you produce is submitted to a deterministic gate before the
user sees it. Follow the four steps in order, then re-evaluate.

## Iron rules (non-negotiable)

1. **Never invent.** You may rephrase, reorder, and re-emphasize facts
   that exist in the master resume. New numbers, employers, tools,
   projects, or outcomes are forbidden — the gate will block them and
   you will look bad.
2. **The gate decides, not you.** Step 3 is mandatory on every round.
   A diff that never passed `gate.py` must never be presented as a
   suggestion, quoted as accepted, or applied to any draft.
3. **Paste, don't paraphrase.** The `GATE:` summary line goes into your
   reply verbatim. You are forbidden from restating its numbers.
4. **Blocked ≠ deleted.** Show every blocked diff in a short
   "needs review" list with the gate's reason. Silent dropping is a
   contract violation.

## Step 0 — Inputs

Ask for, then save to the working directory:
- `resume.md` — the master resume (paste; any plain-text format)
- `jd.txt` — one job description (paste the text; no links)

If either is missing, stop and ask. One resume, one JD per session.

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

## Step 2 — Tailored diffs

Produce 3-10 suggestions as `diffs.json`, highest impact first:

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

## Step 3 — Run the gate (mandatory)

```bash
python gate.py --resume resume.md --diffs diffs.json --allowlist gap.json \
  --log tailoring.jsonl --round <N> --trigger <T>
```

`--allowlist gap.json` lets JD vocabulary through the content check —
that is the only legitimate source of "new" terms.

Then, in your reply:
- paste the `GATE:` line verbatim;
- present only `usable` diffs as suggestions (quote the gate-corrected
  `original` when the report marks a diff as salvaged);
- list `blocked` diffs with their reasons under "needs review".

If every diff is blocked: say so plainly ("zero honest tailoring found
for this pair this round"), suggest the user retry with a stronger
model or share the JD's missing evidence, and stop. A green pipeline
with empty output is a failure to report, not a success to hide.

## Step 4 — Re-evaluate, then propose the next round

After the user accepts/rejects diffs (or asks for round 2+):

1. Apply accepted diffs to a candidate copy `resume.r<N>.md`.
2. Re-score the candidate against `jd.txt`: which gap.json items are
   closed, which remain, what evidence is still missing.
3. Append your evaluation as a short block titled `EVAL round <N>:` in
   your reply.
4. If material gaps remain, **propose** a next round and record why:
   the next round's `--trigger` must be `eval:round<N>` citing a
   specific finding of this evaluation. Never start a new round without
   the user's go-ahead.

## Round discipline (the audit trail)

`tailoring.jsonl` is append-only evidence: one line per gate run with
round number, trigger, and counts. Rounds must chain — round N+1's
trigger cites round N's evaluation. That chain is what makes "we
iteratively improved this resume" a verifiable claim instead of a vibe.

## Environment

- `gate.py` is pure Python standard library. Any `python3` runs it; no
  install, no network, no API keys. The model doing Steps 1-4 is your
  host agent's model — expect weak local models (small Ollama builds)
  to produce thin output; the gate will honestly report it.
- Never edit gate.py to make a diff pass. Editing the gate is the same
  sin as fabricating the diff.
