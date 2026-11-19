# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

statescope: an agent skill (`SKILL.md`), a CLI and a GitHub Action. It infers the state machine a codebase
implements, draws it as a Mermaid `stateDiagram-v2`, and reports invalid transitions under 13 rules,
each cited to a file and line. Plain Python 3.9+, standard library only, no dependencies.

## Layout

- `scripts/extract.py`: infers machines (state sets from enums/unions/CHECK, edges from reads that dominate writes)
- `scripts/audit.py`: the 13 rules; `--markdown`, `--json`, `--strict` (exit 1 on any critical), `--no-fix`
- `scripts/render.py`: `--mermaid` or `--out=file.html`
- `action.yml`: composite Action. Inputs `path`, `strict`, `summary`
- `examples/order-lifecycle/before` (12 findings, 7 critical) and `after` (0 findings) are regression fixtures
- `tests/test_statescope.py`: 76 tests, run with `python3 -m unittest discover -s tests`

## Rules

- Never add a runtime dependency. A false positive is worse than a missed finding.
- Keep the `before`/`after` numbers in the README, `llms.txt` and the blog post in sync with real output.
- Workflow: issue, then branch off `master`, one commit per file, PR, merge. Assign issues and PRs to NHTanvir.
  No co-author lines.

## Distribution and SEO

- GitHub Marketplace: "State Machine Audit (statescope)". Plain "statescope" is taken by a GitHub org.
  Latest release is v0.1.1, and the README pins `NHTanvir/statescope@v0.1.1`. Never move a pushed tag:
  cut a new version instead.
- Blog post: https://naymul.com/state-machine-diagram-from-code/ (repo homepage). The source lives in
  `~/Desktop/naymul-website`.
- Target keywords: "state machine diagram from code", "invalid state transitions", "Prisma state machine".
  The repo has 20 topics, the maximum.

## Known issues

- CI `test (3.9)` fails because `ubuntu-latest` (26.04) has no Python 3.9. Pin that job to `ubuntu-24.04`.
- On a directory with no machine, `audit.py` prints "Every path in this machine is one you declared."
