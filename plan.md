# statescope — research, analysis, and build plan

Date: 2026-11-15. Method inherited from `schemascope/plan.md`: short queries,
`in:name`, `--topic=`. Long descriptive queries return empty on GitHub
regardless of the truth, so they were not used for any conclusion here.

## 1. Objective

A second repo in the `*scope` family. Same shape as schemascope — an agent skill
with zero-dependency Python behind it — chosen by the same criteria and verified
the same way.

## 2. The rule being optimised for

From the schemascope analysis, unchanged:

> A repo earns stars when its output is something the user wants to show other
> people.

1. output is a **visibly impressive artifact** the user wants to post
2. the problem is **embarrassing**, not merely inefficient
3. **zero friction** — a skill, not infrastructure
4. **not absorbed by the vendor, not owned by a first mover**

## 3. The structural pattern

schemascope exists because `drawdb-io/drawdb` has 40,323 stars for making humans
draw schemas **by hand**. The inferred version of that job was unclaimed.

The same shape, verified 2026-11-15:

| Incumbent | Stars | What it makes you do |
|---|---|---|
| `sverweij/state-machine-cat` | 874 | write the state chart in a DSL |
| `statelyai/xstate-viz` | 454 | visualise a machine you already wrote |
| `statelyai/sketch` | 86 | draw and simulate XState machines |
| `lucmartens/xstate-plantuml` | 70 | render XState as PlantUML |

1,400+ stars for drawing a machine a human has already written down. Nothing
infers one from ordinary code.

## 4. Verification

### 4.1 The inferred slice is empty

| Query | Total | Top result | Verdict |
|---|---|---|---|
| `fsm-inference in:name,description` | 17 | nothing relevant | empty |
| `state-machine-diagram in:name` | 35 | 3★, student UML coursework | empty |
| `status-transition in:name` | 17 | 3★ Magento module | empty |
| `statechart in:name` | 584 | 1,628★ `godot-statecharts` — a runtime library | different job |
| `lifecycle-diagram in:name` | 37 | 3,930★ — React lifecycle, unrelated | different domain |
| `state-machine topic:claude-skill` | 11 | 392★ `Raja0sama/vibex` | see 4.2 |

### 4.2 The one real competitor — `Raja0sama/vibex` (392★, Nov 2026)

Same playbook: zero dependencies, standalone HTML, skill distribution, six
diagram types. Its `lifecycle` diagram is described as "every state a thing can
reach and every legal move between them, with actor, event, guard and side
effect on each arrow".

**Its import column says `hand-authored`.** vibeX infers `erd` from Prisma and
`endpoints` from OpenAPI; `lifecycle`, `c4`, `sequence` and `links` are all
hand-authored JSON specs. It emits no findings on the lifecycle — it draws what
you typed.

The gap is therefore precise: **vibeX draws the machine you describe; statescope
draws the machine you shipped, and says what is wrong with it.** The second half
is the half that earns the screenshot.

### 4.3 Rejected on evidence

| Idea | Killed by |
|---|---|
| Supabase/Postgres RLS audit | `supabase/splinter` 292★ is **official** (vendor-absorbed), `supashield` 105★, `database-sentinel` 50★, and the exact agent-skill version already shipped twice — both at 1★ |
| Threat model from a repo | `fr33d3m0n/threat-modeling` 353★, "AI-native, LLM-driven, code-first skill", plus `awslabs/threat-modeling-mcp-server` 127★ |
| MCP / agent-tool security | `cisco-ai-defense/mcp-scanner` 1,118★. Cisco is in it |
| Money-handling audit | `theigwe/moneyproof` shipped it as a Claude skill and scored 1★; no artifact to post |
| Test-quality audit | fails criterion 1 — a scorecard about your own sloppiness is what scored 0–4 eighteen times in the schemascope data |
| Generic diagram skill | settled and settled high: 6,333★ / 5,265★ / 3,404★ / 2,648★ / 670★ / 420★ |

### 4.4 Name availability

| | GitHub | npm | PyPI |
|---|---|---|---|
| `statescope` | 13 repos, max 8★ (bioinformatics, unrelated) | taken | taken |
| `statemap` | **245★ real adjacent tool** — avoided | — | — |

Package collisions are irrelevant: distribution is a skill plus a vendored
stdlib script, exactly as with schemascope, whose PyPI name is also taken.

## 5. Problem validation

Independent of the market analysis, the defect class is real and mechanical:

- An enum constrains a column. Nothing constrains the order of writes to it.
- An agent writing one handler has no reason to consider the other ten, so each
  handler guards only the case in front of it.
- The machine is therefore never written down anywhere, which is exactly why
  nobody can see that it is wrong by reading the code.

The example in `examples/order-lifecycle/before` is 4 files and 10 writes. It
contains, without exaggeration: a terminal state that can be escaped two ways, a
transition that runs backwards, five writes with no guard, an admin endpoint
that accepts any string, a dead state, and no history. That is one afternoon of
ordinary agent output.

## 6. Product

### 6.1 Inputs (no config, no drivers)

State sets from Prisma enums, TypeScript unions and enums, `as const` arrays,
Python `Enum`, PHP 8.1 enums, SQL `CHECK` constraints, MySQL/Postgres enums.
Transitions from the code: a read of the state that dominates a write is an
edge; a write with no such read is `* -> state`. A declared `ALLOWED` table, if
one exists, is read instead and marked `declared`.

### 6.2 Outputs

- ranked findings, each cited to `file:line`
- a transition table as the fix, in the language the machine was declared in
- a Mermaid `stateDiagram-v2` that GitHub renders inline
- one self-contained HTML file, light and dark

### 6.3 The design decision that matters

The idiomatic *correct* pattern — one `transition()` function with an allow-list
— would have been flagged by the first draft of `unconstrained_write` and
`unguarded_write`, because the write it performs is `status: to` with a variable.
A tool that flags the correct answer is uninstalled the same day.

So validation-in-scope suppresses both rules, and declared tables are read as
the machine. `examples/order-lifecycle/after` is the regression test for this:
CI fails if it ever reports anything.

## 7. Launch

1. README hero is the `before` diagram — red escapes, orange unguarded writes,
   grey dead state — rendered by GitHub itself from emitted Mermaid.
2. The install line is one paste to an agent, via `llms.txt`.
3. Cross-link with schemascope: that one audits the schema that declares the
   enum, this one audits what the code does with it. Each sells the other.
