# The 13 rules

Each rule states what it looks for, why it is worth a finding, and what the fix
is. Severity is about how quietly the defect corrupts data, not how hard it is
to fix.

Every finding carries the file and line that allows the path. Where a rule can
be wrong, that is said here rather than hidden.

---

## Critical

### `terminal_state_escape`

**Fires when** a transition leaves a state in the terminal vocabulary
(`refunded`, `cancelled`, `completed`, `closed`, `delivered`, `failed`,
`expired`, `archived`, `deleted`, `rejected`, `fulfilled`, `settled`, `done`,
`finished`, `terminated`, `revoked`, `void`, `returned`).

**Why.** A terminal state is a promise to the rest of the system. Accounting has
reconciled the refund. The warehouse has closed the pick. The customer got the
email. Moving the row out of that state re-opens all of it with no record, and
every report that already counted it is now wrong in a way nothing will flag.
The row looks ordinary afterwards, which is what makes it expensive.

**Fix.** The generated transition table, with the terminal states mapped to `[]`.
If the reversal is deliberate, it is a different state — `reopened`, not
`pending` — so that reports can tell a fresh order from a resurrected one.

**When it is wrong.** A workflow that genuinely re-opens, like a support ticket.
The name is then the problem, not the edge.

### `unconstrained_write`

**Fires when** the state field is assigned a value that is not a known member —
`data: { status }`, `$order->status = $request->status` — and no allow-list
check dominates the write.

**Why.** The enum constrains the column; it does not constrain the call. The set
of reachable states is not what you declared, it is whatever a caller can spell.
This is the write that puts a state into production that your own diagram does
not contain, and it is usually one line in an admin endpoint.

**Fix.** Accept a `to` state and validate it against the table before writing.
Validation anywhere above the write in the same scope — `ALLOWED[from].includes(to)`,
`in_array`, `Object.values(X).includes`, `z.enum`, a `canTransition` call — is
recognised and the finding is suppressed.

### `unguarded_write`

**Fires when** a state is written and no read of the state field dominates the
write, and the target is not the initial state.

**Why.** No comparison protects it, so *every* state reaches the target,
including the terminal ones. The real machine is fully connected; the diagram in
your head is fiction. This is the most common defect in generated state code,
because an agent writing one handler has no reason to think about the other ten.

**Fix.** Put the expected state in the `WHERE` clause of the update, which both
guards and resolves the race in one statement.

**When it is wrong.** A guard expressed in a way the heuristics miss — a state
held in a variable several functions up, a check inside a decorator. The finding
cites the write, so one click settles it. Creation sites (`create`, `insert`,
`new`, `register`) and the initial state are already excluded.

---

## High

### `backwards_transition`

**Fires when** both ends of an edge are in `RANK` and the target ranks lower
than the source — `shipped -> paid`, `delivered -> pending`.

**Why.** Side effects do not reverse when the column does. The email went out,
the webhook fired, the stock moved, the payout was scheduled. Reversing the
state tells the system none of that happened.

**Fix.** A distinct state for the reversal, with its own name and its own edges.

**Note.** Only well-known lifecycle words are ranked. Unfamiliar vocabulary is
never called backwards — extend `RANK` rather than loosening this.

### `concurrent_write_race`

**Fires when** a guarded transition reads the state and then writes it without
the state appearing in the `WHERE` clause, and without a lock.

**Why.** The read and the write are two round trips. Between them the row can
move, so two callers that both read the same state will both write, and the
second one wins silently. Webhook retries and double-clicked buttons do exactly
this, which is why the bug reports arrive on the busiest day.

**Fix.**

```ts
const { count } = await prisma.order.updateMany({
  where: { id, status: "paid" },      // not just { id }
  data:  { status: "shipped" },
});
if (count === 0) throw new ConcurrentTransition(id);
```

The database refuses the second write instead of the application hoping it never
happens. A lock (`SELECT … FOR UPDATE`, `lockForUpdate`, `select_for_update`) or
a version column also satisfies this rule.

### `bypass_write`

**Fires when** a transition helper exists (a function named like `transition`,
`setStatus`, `changeStatus`, `markAs`, `advance`) and writes to the state happen
in files that do not contain it.

**Why.** The helper is where the rules live, so the rules only apply to callers
who remember it exists. Every direct write is a second, undocumented
implementation of the machine, and the two drift the moment one gets a new
condition.

**Fix.** Make the field unwritable from outside the module that owns the helper,
or move the check into the database with a trigger. Going around it should be
impossible, not merely discouraged.

---

## Medium

### `unreachable_state`

**Fires when** no transition targets a state and it is not the initial state.

**Why.** Nothing can put a row there, yet the state is declared and code
elsewhere may branch on it. Either a transition was lost in a refactor and rows
are stuck one step earlier, or the state is vestigial and every `if` mentioning
it reads as live logic while being dead weight.

**Fix.** Add the transition, or delete the state.

### `dead_state`

**Fires when** a state is declared and never written anywhere.

**Why.** It survives in the enum, in the database constraint, and in the mental
model of everyone who reads the schema — but no row will ever hold it. Dead
states are how a diagram stops matching a system: the picture is bigger than the
behaviour, and the difference is invisible.

**Fix.** Delete it, or implement the path that sets it. The initial state is
exempt, because the column default writes it rather than the code.

### `orphan_state`

**Fires when** a state is written and never read in any comparison, and it is
not terminal.

**Why.** Rows arrive and nothing asks about it. No guard reads it, no query
filters on it, no report counts it. Either it is a write-only label that would
be better as a timestamp, or the handling meant to read it was never written.

**Fix.** Add the guard that reads it, or stop writing a state nothing consumes.

### `no_terminal_state`

**Fires when** no state is in the terminal vocabulary and every state has an
outgoing edge.

**Why.** A lifecycle with no absorbing state cannot say that a thing is done.
Retention, archival, reconciliation and reporting all need a point after which
nothing changes. Without one, every row stays live forever and every query has
to carry a date range to pretend otherwise.

**Fix.** Name the end. Even `archived` with no outgoing edges is enough.

### `missing_transition_log`

**Fires when** no write to the state field is accompanied by a timestamp or an
audit write.

**Why.** The column holds the current state and nothing else. The first time
someone asks why this was refunded, who cancelled it, or when it shipped, the
answer is not in the database. A state column is a cache of the last event; if
the events are never stored, the history is gone the moment it is overwritten.

**Fix.** A `status_changed_at` column is the minimum. An append-only history
table — `from`, `to`, `actor_id`, `reason`, `at` — is the thing you actually
wanted, and it is the table that answers support tickets.

---

## Low

### `duplicate_guard`

**Fires when** the same edge is implemented in two or more files.

**Why.** The same rule written twice drifts. One copy gets a new condition, the
other does not, and from then on behaviour depends on which entry point the
caller used.

**Fix.** One table, one function.

### `literal_state_write`

**Fires when** writes use a bare string instead of the enum member.

**Why.** A typo in a quoted state is a value the compiler accepts and the
database rejects at the boundary, if at all. Referring to the member by name
moves that failure into the editor.

**Fix.** `data: { status: OrderStatus.SHIPPED }`.

**Note.** Suppressed for state sets that have no member names to refer to —
SQL `CHECK` constraints, `as const` arrays and TypeScript unions.
