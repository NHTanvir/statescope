# Contributing

Thanks for looking. One principle governs everything here.

## A false positive is worse than a missed finding

This tool tells people their code allows something it should not. If it says
that and it is wrong, they stop believing the other twelve findings, and the
tool is worse than nothing. So:

- **Every finding must carry a file and a line.** No exceptions. A finding
  nobody can click is a finding nobody acts on, and one that cannot be checked
  cannot be corrected.
- **Prefer silence to a guess.** `backwards_transition` only fires on lifecycle
  words that are actually ranked in `RANK`. If the vocabulary is unfamiliar, the
  rule says nothing. That is the correct behaviour — extend `RANK` instead of
  loosening the rule.
- **A new rule needs a test that fires and a test that does not.** The second
  one is the important one. See `test_forward_transition_is_not_backwards` and
  `test_validated_free_write_is_not_reported`.
- **The corrected example must stay at zero.** `examples/order-lifecycle/after`
  audits clean, and CI fails if it ever does not. If your rule fires on it, your
  rule is flagging good code — fix the rule.

## The shape of the thing

- `scripts/extract.py` finds the states and the transitions. Nothing in here
  judges anything.
- `scripts/audit.py` judges. Every rule is a function taking `(machine, out)`.
- `scripts/render.py` draws. It must never change a finding.
- Standard library only, Python 3.9+. No dependencies, ever — it is the reason
  this installs in one command inside someone else's agent.

## Running it

```bash
python3 -m unittest discover -s tests -v
python3 scripts/audit.py examples/order-lifecycle/before
python3 scripts/audit.py examples/order-lifecycle/after --strict
```

## Reporting a false positive

Open an issue with the smallest snippet that triggers it and what the code
actually guarantees. That is the most useful kind of issue this project can get,
and it will be treated as a bug, not a preference.
