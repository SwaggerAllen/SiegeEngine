---
name: review-requirements
description: Review a requirements draft. Reads `get_review_context` for the scope, produces a `<review>` XML block per the parser contract, writes it as review.md, updates state JSON, commits, and pushes. Triggers automatically after a `draft-requirements` or on manual `/review_requirements <id>`.
thinking_effort: max
---

# Review a requirements

You are reviewing one drafted requirements. The output is a single
`<review>` XML block (see `siege_mcp/parsers/review_xml.py` for the
exact schema). Score is 0-100; bands are 0-30 (rework), 31-60
(structural fixes), 61-85 (refinements), 86-100 (ready).

## Inputs

- `ref` — git ref
- `comp_id` — stable id of the scope

## Steps

1. **Read the draft state.** Call `mcp__siegeengine__get_state` to
   confirm the scope is in `drafted` status with a valid draft block.
   If it's already `reviewed` or `approved`, ask the user whether to
   re-review (most of the time this is a mistake).
2. **Fetch review context.** Call
   `mcp__siegeengine__get_review_context(ref=$ref, tier="requirements",
   scope={"comp_id": $comp_id, "tier": "requirements"}, draft_sha=<draft.body_sha256 from state>)`.
3. **Compose the review.** Produce one `<review>...</review>` block
   following the schema:
   - `<intro>` — 3-6 sentence "how close to finished" read (display only)
   - `<score>` — integer 0-100
   - `<handles-structure>` — per-finding `<finding id="hN">` entries
   - `<architectural-decisions>` — same shape; rename to
     "decomposition axis critique" on tiers without explicit tech
     decisions (expansion / requirements / fanin)
4. **Validate inline.** Run `parse_review` mentally — if any section
   is missing or empty, fix and re-emit.
5. **Write the review** to `requirements/$comp_id/review.md`.
6. **Materialize state JSON inline** (pure `python3` stdlib). Extracts
   `<score>` and `<intro>` from the review with a regex, computes
   sha256, updates state JSON's `review` block, bumps nonce. Refuses
   to write if `<score>` is missing or out of range, or if state
   isn't in `drafted`:

   ```bash
   REVIEW_PATH=requirements/$comp_id/review.md
   STATE_PATH=state/requirements/$comp_id.json
   python3 - "$REVIEW_PATH" "$STATE_PATH" <<'PY'
import hashlib, json, re, secrets, sys, time
review_path, state_path = sys.argv[1:3]
review = open(review_path).read()
m = re.search(r"<score>\s*(\d+)\s*</score>", review)
if not m:
    sys.exit("error: <score> missing or unparseable in review")
score = int(m.group(1))
if not 0 <= score <= 100:
    sys.exit(f"error: <score> out of range 0..100: {score}")
intro_m = re.search(r"<intro>(.*?)</intro>", review, re.DOTALL)
intro = (intro_m.group(1) if intro_m else "").strip()
if not intro:
    sys.exit("error: <intro> missing or empty")
state = json.loads(open(state_path).read())
if state.get("status") != "drafted":
    sys.exit(f"error: cannot review a scope with status={state.get('status')!r}")
sha = hashlib.sha256(review.encode()).hexdigest()
nonce_bits = secrets.randbits(128)
alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUV"
state["nonce"] = "".join(reversed([alphabet[(nonce_bits >> (5*i)) & 0x1F] for i in range(26)]))
state["status"] = "reviewed"
state["review"] = {
    "body_path": review_path,
    "body_sha256": sha,
    "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "score": score,
    "reviewer_metadata": {},
}
open(state_path, "w").write(json.dumps(state, indent=2, sort_keys=True) + "\n")
print(json.dumps({"state_path": state_path, "score": score, "intro_first_sentence": intro.split(".", 1)[0]}))
PY
   ```
7. **Stage both files**, commit:
   `review(requirements/$id): score=<N> — <intro first sentence>`
8. **Push.**

## Don't

- Don't review a scope that isn't `drafted` (without confirmation).
- Don't omit the `<intro>` or emit a non-integer `<score>`.
- Don't reuse a stale `draft_sha` — re-fetch state if you've been
  idle and someone might have re-drafted.

## Output

One line: `score=<N> — <intro first sentence>`, plus the commit sha.
