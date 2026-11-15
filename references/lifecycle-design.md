# How to design a lifecycle that stays legible

Notes for the agent, and for whoever inherits the code. These are the decisions
that determine whether the machine is still understandable in a year.

## Keep the machine in one place

A lifecycle implemented as scattered `if` statements is not a lifecycle, it is a
rumour. One table, one function, every caller going through it:

```ts
const ALLOWED: Record<OrderStatus, OrderStatus[]> = { … };
```

The test is simple: can someone answer "what can happen to a paid order?" by
reading one screen? If they have to grep, the machine has no home.

## Name states after what is true, not after what happened

`paid` is a fact about the order. `payment_webhook_received` is a fact about your
infrastructure. The first survives a change of payment provider; the second is
already a lie once you add a second one.

Say what the row *is*, in the vocabulary the business uses out loud.

## Make the end states real ends

Every lifecycle needs at least one state with no outgoing edges. It is what lets
you archive, reconcile, and stop paying attention. If the business "re-opens"
things, that is a new state (`reopened`), not an edge back to the beginning —
because a report that cannot tell a fresh order from a resurrected one is a
report that is quietly wrong.

## Do not encode two dimensions in one column

`cancelled_by_user`, `cancelled_by_admin`, `cancelled_fraud` is one state and a
reason, not three states. The moment you multiply the reason into the state
name, every guard has to list all the variants and one of them always gets
forgotten.

```
status  = cancelled
reason  = fraud
```

Two columns, and the machine stays small enough to draw.

## Store the move, not just the position

The state column tells you where a row is. It cannot tell you how it got there,
and that is the question every support ticket asks. An append-only table —
`from`, `to`, `actor`, `reason`, `at` — costs one insert and answers all of it.
It is also the only way to recover from a bad deploy that moved rows wrongly.

## Guard in the database, not only in the application

An `if` in one language protects one codebase. Jobs, migrations, admin consoles
and the psql session someone opens at midnight all bypass it. Put the expected
state in the `WHERE` clause so the database does the checking:

```sql
UPDATE "order" SET status = 'shipped'
 WHERE id = $1 AND status = 'paid';
-- 0 rows updated means someone else moved it first. That is information.
```

## Draw it before adding a state

Adding a state is a change to a graph, not a change to a list. Draw the graph
first: the new state needs at least one way in, a defined way out or a reason it
is terminal, and an answer for what every existing guard should do when it sees
it. Most "we need a new status" requests are a new column once drawn.

## Diagram style

When rendering for a human:

- **Left to right** for a pipeline, top to bottom only if there are more than
  about eight states.
- **One colour, one meaning.** Red for a path that should not exist, grey for
  something declared and never used. Do not colour by category — the eye reads
  colour as severity whether you meant it or not.
- **Label an edge only when the label adds something.** `paid --> shipped` needs
  no label. `refunded --> pending : escapes refunded` does.
- **Show the illegal paths.** A diagram with only the happy path is marketing,
  and it is the diagram everyone already has in their head. The useful picture is
  the one that is worse than expected.
