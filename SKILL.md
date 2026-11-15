---
name: statescope
description: Infer the state machine a codebase actually implements, draw it, and find the illegal paths. Use when the user asks about a status field, a lifecycle, a workflow, a state machine, an enum of states, order/subscription/ticket statuses, or a state diagram - or right after you have written or changed code that sets a status. Finds terminal states that can be escaped, writes no guard protects, transitions that run backwards, read-then-write races, and dead or unreachable states, and emits a transition table that fixes them plus a Mermaid state diagram.
---

# statescope

Read the code, infer the state machine it really implements, report the paths
that should not exist, and draw it.

## When to use this

- the user asks about a `status`/`state` field, a lifecycle, a workflow, or a state diagram
- the user asks why a row is in an impossible state, or why one moved backwards
- you are about to add or change a status value, an enum member, or a transition
- **immediately after you write code that sets a status** — review your own work
  before saying it is done

## How to run it

The scripts live in `scripts/` next to this file. They need Python 3.9+ and
nothing else. Resolve `<skill>` to this skill's directory.

```bash
# 1. the audit -- always run this first
python3 <skill>/scripts/audit.py <path>

# 2. the diagram
python3 <skill>/scripts/render.py <path> --mermaid

# 3. a single shareable HTML file with both
python3 <skill>/scripts/render.py <path> --out=state-review.html
```

`<path>` is a directory (the repo root, or one service) or a single file. Point
it at the whole project first; narrow only if it finds several machines and the
user cares about one.

Other flags: `--markdown` (for a PR comment), `--json` (for tooling),
`--strict` (exit 1 on any critical, for CI), `--no-fix` (findings without the
fix code), `--machine=NAME` on `render.py` (draw one machine when there are
several).

## How to report the result

1. **Lead with the machine, then the counts.** "`OrderStatus.status`, 7 states,
   11 transitions: 7 critical, 2 high, 2 medium, 1 low."
2. **Show the diagram** whenever the user asked anything about structure, or
   whenever there is more than one illegal path. It is the output that makes the
   problem obvious; do not bury it under prose.
3. **Show the criticals in full**, each with the file and line that allows it.
   The line number is the whole point — never paraphrase a finding without it.
4. **Summarise the rest by rule**, not one by one. "Five writes have no guard"
   beats five near-identical paragraphs.
5. **Offer the transition table** as the fix, once, at the end. Do not apply it.

## Rules that matter

**Never apply a fix without being asked.** Which moves are legal is a product
decision, not a code-style one. A table that forbids `delivered -> shipped` is
correct for most shops and wrong for the one that reships lost parcels. Ask.

When the user does ask you to apply it:

1. Add the table and the `transition()` function first, with nothing calling it.
2. Move call sites over one at a time, starting with the one the user names.
3. Put the state in the `WHERE` clause of the update, not only in an `if` above
   it — otherwise the race survives the refactor.
4. Add the history table before the first migration that depends on it.
5. Delete a state from the enum only after confirming no rows hold it. On
   PostgreSQL, removing an enum member needs a new type and a rewrite.

A finding is a judgement, not a fact:

- `backwards_transition` on a deliberate re-open flow is correct behaviour with
  a misleading name. Say so rather than reporting a number you do not believe.
- `missing_transition_log` on an internal tool nobody audits is noise.
- `* -> state` means no guard **was recognised**, not that none exists. Check
  the cited line before telling the user their code is unguarded; if the guard
  is real and expressed unusually, say that the tool missed it.
- If `extract.py` finds no machine, say so plainly. Do not invent one from the
  enum alone — an unused enum is not a lifecycle, and that is a finding in
  itself worth mentioning.

## Reference

- [`references/audit-rules.md`](references/audit-rules.md) — all 13 rules, each with rationale and fix
- [`references/lifecycle-design.md`](references/lifecycle-design.md) — how to design a lifecycle that stays legible
