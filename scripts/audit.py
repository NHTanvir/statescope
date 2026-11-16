#!/usr/bin/env python3
"""Audit an inferred state machine for paths that should not exist.

Reads the JSON emitted by extract.py and reports ranked findings. Every finding
carries the file and line that allows the path, because a claim about control
flow that you cannot click is a claim nobody acts on.

Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

TERMINAL_WORDS = {
    "refunded", "cancelled", "canceled", "completed", "complete", "closed",
    "delivered", "failed", "expired", "archived", "deleted", "rejected",
    "fulfilled", "settled", "done", "finished", "terminated", "revoked",
    "void", "voided", "returned",
}
RANK = {
    "draft": 0, "new": 0, "created": 0, "initialized": 0, "open": 5,
    "pending": 10, "awaiting_payment": 10, "unpaid": 10, "queued": 10,
    "scheduled": 12, "submitted": 15, "in_review": 18, "processing": 20,
    "in_progress": 20, "inprogress": 20, "running": 20, "started": 20,
    "active": 22, "trialing": 22, "confirmed": 25, "approved": 25, "verified": 25,
    "paid": 30, "settled": 32, "packed": 35, "ready": 36, "shipped": 40,
    "in_transit": 45, "out_for_delivery": 48, "delivered": 50,
    "fulfilled": 58, "completed": 60, "complete": 60, "done": 60,
    "finished": 60, "closed": 70, "archived": 80,
}
LOG_HINT = re.compile(
    r"(_at\b|\bat:|changed_?at\b|moved_?at\b|\blog\b|audit|history|event|track|emit|record|journal|"
    r"transition_log|statusHistory|status_history)", re.I
)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_WORDS


def rank(state: str):
    return RANK.get(state)


def plural(n: int) -> str:
    return "" if n == 1 else "s"


def finding(sev, rule, machine, msg, why, fix, states=None, evidence=None) -> dict:
    return {
        "severity": sev,
        "rule": rule,
        "machine": machine,
        "states": states or [],
        "message": msg,
        "why": why,
        "fix": fix,
        "evidence": evidence or [],
    }


def ev(items, limit: int = 4) -> list:
    out, seen = [], set()
    uniq = []
    for e in items:
        key = (e.get("file"), e.get("line"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    for e in uniq[:limit]:
        out.append({
            "file": e.get("file"),
            "line": e.get("line"),
            "guard_line": e.get("guard_line"),
            "snippet": (e.get("snippet") or "")[:140],
        })
    return out


# --------------------------------------------------------------------------
# the fix: a transition table generated from the states that were found
# --------------------------------------------------------------------------

def lang_of(machine: dict) -> str:
    kind = machine.get("kind", "")
    if kind in {"py_enum"}:
        return "python"
    if kind in {"php_enum"}:
        return "php"
    if kind in {"sql_check", "sql_enum_column", "sql_enum_type"}:
        return "sql"
    return "ts"


def legal_edges(machine: dict) -> dict:
    """A defensible default table: forward by rank, terminal states closed."""
    states = machine["states"]
    ranked = sorted(
        [s for s in states if rank(s) is not None], key=lambda s: rank(s)
    )
    exits = [s for s in states if is_terminal(s) and rank(s) is None]
    table = {}
    for s in states:
        if is_terminal(s):
            table[s] = []
            continue
        nxt = []
        if s in ranked:
            i = ranked.index(s)
            if i + 1 < len(ranked):
                nxt.append(ranked[i + 1])
        nxt += exits
        table[s] = nxt
    return table


def table_fix(machine: dict) -> str:
    table = legal_edges(machine)
    name = machine["name"]
    field = machine["field"]
    lang = lang_of(machine)
    lits = machine.get("literals", {})

    def lit(s):
        return lits.get(s, s)

    if lang == "python":
        rows = "\n".join(
            f"    {name}.{lit(s).upper()}: [{', '.join(f'{name}.{lit(t).upper()}' for t in ts)}],"
            for s, ts in table.items()
        )
        return (
            f"ALLOWED: dict[{name}, list[{name}]] = {{\n{rows}\n}}\n\n"
            f"def transition(obj, to: {name}) -> None:\n"
            f"    if to not in ALLOWED[obj.{field}]:\n"
            f"        raise IllegalTransition(obj.{field}, to)\n"
            f"    # one statement, and the database refuses a second caller\n"
            f"    updated = (Order.objects\n"
            f"        .filter(pk=obj.pk, {field}=obj.{field})\n"
            f"        .update({field}=to, {field}_changed_at=now()))\n"
            f"    if not updated:\n"
            f"        raise ConcurrentTransition(obj.pk)"
        )
    if lang == "php":
        rows = "\n".join(
            f"        {name}::{lit(s).title()}->value => ["
            + ", ".join(f"{name}::{lit(t).title()}->value" for t in ts)
            + "],"
            for s, ts in table.items()
        )
        return (
            f"private const ALLOWED = [\n{rows}\n    ];\n\n"
            f"public function transition(Order $order, {name} $to): void\n{{\n"
            f"    if (! in_array($to->value, self::ALLOWED[$order->{field}], true)) {{\n"
            f"        throw new IllegalTransition($order->{field}, $to->value);\n"
            f"    }}\n"
            f"    $changed = Order::where('id', $order->id)\n"
            f"        ->where('{field}', $order->{field})\n"
            f"        ->update(['{field}' => $to->value, '{field}_changed_at' => now()]);\n"
            f"    if ($changed === 0) {{\n"
            f"        throw new ConcurrentTransition($order->id);\n"
            f"    }}\n}}"
        )
    if lang == "sql":
        rows = "\n".join(
            f"    ('{lit(s)}', '{lit(t)}')," for s, ts in table.items() for t in ts
        )
        return (
            f"CREATE TABLE {field}_transition (\n"
            f"  from_{field} text NOT NULL,\n"
            f"  to_{field}   text NOT NULL,\n"
            f"  PRIMARY KEY (from_{field}, to_{field})\n);\n\n"
            f"INSERT INTO {field}_transition (from_{field}, to_{field}) VALUES\n"
            f"{rows}".rstrip(",")
            + ";\n\n-- then make the illegal path impossible rather than discouraged\n"
            f"CREATE TRIGGER {field}_guard BEFORE UPDATE OF {field} ON \"order\"\n"
            f"  FOR EACH ROW WHEN OLD.{field} <> NEW.{field}\n"
            f"  EXECUTE FUNCTION assert_{field}_transition();"
        )
    rows = "\n".join(
        f"  {lit(s)}: [{', '.join(repr(lit(t)).replace(chr(39), chr(34)) for t in ts)}],"
        for s, ts in table.items()
    )
    return (
        f"const ALLOWED: Record<{name}, {name}[]> = {{\n{rows}\n}};\n\n"
        f"export async function transition(id: string, to: {name}) {{\n"
        f"  const from = Object.keys(ALLOWED).filter((s) =>\n"
        f"    ALLOWED[s as {name}].includes(to)) as {name}[];\n"
        f"  // the WHERE does the checking, so two concurrent callers cannot both win\n"
        f"  const {{ count }} = await prisma.order.updateMany({{\n"
        f"    where: {{ id, {field}: {{ in: from }} }},\n"
        f"    data: {{ {field}: to, {field}ChangedAt: new Date() }},\n"
        f"  }});\n"
        f"  if (count === 0) throw new IllegalTransition(id, to);\n}}"
    )


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def rule_terminal_escape(m: dict, out: list) -> None:
    for t in m["transitions"]:
        if t["from"] == "*" or not is_terminal(t["from"]):
            continue
        out.append(finding(
            "critical", "terminal_state_escape", m["name"],
            f"{t['from']} -> {t['to']} is reachable. {t['from']} is a terminal state.",
            f"{t['from']} is where a thing stops. Code downstream of it assumes it is "
            f"settled: refunds are reconciled, invoices are closed, the warehouse has "
            f"stopped caring. Moving it back to {t['to']} re-opens all of that with no "
            f"record that it happened, and every report that already counted it is now "
            f"wrong in a way nothing will flag.",
            table_fix(m), [t["from"], t["to"]], ev(t["evidence"]),
        ))


def rule_unconstrained_write(m: dict, out: list) -> None:
    free = m.get("free_writes") or []
    if not free:
        return
    out.append(finding(
        "critical", "unconstrained_write", m["name"],
        f"{len(free)} write(s) put an unchecked value into {m['field']}.",
        f"The enum constrains the column, not the call. `{free[0]['value']}` arrives "
        f"from the caller and goes straight in, so the set of reachable states is not "
        f"the enum — it is whatever any caller can spell. This is the write that puts "
        f"a state in production that your own diagram does not contain.",
        table_fix(m), [], ev(free),
    ))


def rule_unguarded_write(m: dict, out: list) -> None:
    terminals = [s for s in m["states"] if is_terminal(s)]
    for t in m["transitions"]:
        if t["kind"] != "unguarded" or t["to"] == m.get("initial"):
            continue
        others = [x for x in terminals if x != t["to"]]
        reach = ", ".join(others[:3]) if others else "any state"
        out.append(finding(
            "critical" if others else "high", "unguarded_write", m["name"],
            f"* -> {t['to']} : nothing reads {m['field']} before this write.",
            f"No comparison protects it, so every state reaches {t['to']} — including "
            f"{reach}. The transition is whatever the caller happens to invoke, which "
            f"means the real machine is fully connected and the diagram in your head is "
            f"fiction. This is the single most common defect in generated state code.",
            table_fix(m), [t["to"]], ev(t["evidence"]),
        ))


def rule_backwards(m: dict, out: list) -> None:
    for t in m["transitions"]:
        a, b = rank(t["from"]), rank(t["to"])
        if t["from"] == "*" or a is None or b is None or b >= a:
            continue
        out.append(finding(
            "high", "backwards_transition", m["name"],
            f"{t['from']} -> {t['to']} moves the lifecycle backwards.",
            f"{t['from']} happens after {t['to']}, so this edge un-does work that "
            f"other systems have already acted on. Side effects do not reverse when "
            f"the column does: the email went out, the webhook fired, the stock moved. "
            f"If the reversal is deliberate it belongs as its own state, with its own "
            f"name, so that reports can tell the two apart.",
            table_fix(m), [t["from"], t["to"]], ev(t["evidence"]),
        ))


def rule_race(m: dict, out: list) -> None:
    bad = [
        t for t in m["transitions"]
        if t["kind"] == "guarded" and not t.get("predicate")
    ]
    if any(t["kind"] == "declared" for t in m["transitions"]) and not bad:
        return
    if not bad:
        return
    evs = [e for t in bad for e in t["evidence"]]
    pairs = ", ".join(f"{t['from']}->{t['to']}" for t in bad[:4])
    out.append(finding(
        "high", "concurrent_write_race", m["name"],
        f"{len(bad)} transition(s) check the state in memory, then write: {pairs}.",
        f"The read and the write are two round trips. Between them the row can move, "
        f"so two callers that both read the same state will both write, and the second "
        f"one wins silently. Webhook retries and double-clicked buttons do exactly "
        f"this. Putting {m['field']} in the WHERE clause makes the database refuse the "
        f"second write instead of the application hoping it never happens.",
        table_fix(m), [], ev(evs),
    ))


def rule_bypass(m: dict, out: list) -> None:
    helpers = m.get("helpers") or []
    if not helpers:
        return
    helper_files = {h["file"] for h in helpers}
    outside = [w for w in m["writes"] if w["file"] not in helper_files]
    if not outside:
        return
    out.append(finding(
        "high", "bypass_write", m["name"],
        f"A transition helper exists ({helpers[0]['name']} in {helpers[0]['file']}) "
        f"but {len(outside)} write(s) go around it.",
        "The helper is where the rules live, so the rules only apply to callers that "
        "remember it exists. Every direct write is a second, undocumented implementation "
        "of the machine. Make the field private to the module that owns the helper, or "
        "move the check into the database, so that going around it is not possible "
        "rather than merely discouraged.",
        table_fix(m), [], ev(outside),
    ))


def rule_unreachable(m: dict, out: list) -> None:
    incoming = {t["to"] for t in m["transitions"]}
    has_wild = any(t["from"] == "*" for t in m["transitions"])
    for s in m["states"]:
        if s in incoming or s == m.get("initial") or has_wild:
            continue
        out.append(finding(
            "medium", "unreachable_state", m["name"],
            f"{s} has no incoming transition.",
            f"Nothing in the codebase can put a row into {s}, yet it is declared and "
            f"code elsewhere may branch on it. Either a transition was lost in a "
            f"refactor and rows are stuck one step earlier, or the state is vestigial "
            f"and every `if` that mentions it is dead weight that reads as live logic.",
            f"# remove {s} from {m['name']}, or add the transition that reaches it",
            [s], [{"file": m["declared_in"]["file"], "line": m["declared_in"]["line"],
                   "snippet": f"{m['name']} declares {s}"}],
        ))


def _written(m: dict) -> set:
    return {w["state"] for w in m["writes"]} | {
        t["to"] for t in m["transitions"] if t["kind"] == "declared"
    }


def _read(m: dict) -> set:
    return {r["state"] for r in m["reads"]} | {
        t["from"] for t in m["transitions"] if t["kind"] == "declared"
    }


def rule_dead_state(m: dict, out: list) -> None:
    written = _written(m)
    for s in m["states"]:
        # the initial state is written by the column default, not by the code
        if s in written or s == m.get("initial"):
            continue
        out.append(finding(
            "medium", "dead_state", m["name"],
            f"{s} is declared but never written anywhere.",
            f"No line in the codebase assigns {s}. It survives in the enum, in the "
            f"database constraint and in the mental model of everyone who reads the "
            f"schema, but no row will ever hold it. Dead states are how a diagram "
            f"stops matching the system: the picture is bigger than the behaviour.",
            f"# delete {s} from {m['name']}, or implement the path that sets it",
            [s], [{"file": m["declared_in"]["file"], "line": m["declared_in"]["line"],
                   "snippet": f"{m['name']} declares {s}"}],
        ))


def rule_orphan_state(m: dict, out: list) -> None:
    read = _read(m)
    written = _written(m)
    for s in m["states"]:
        # a terminal state is meant to have nothing branching out of it
        if s in read or s not in written or is_terminal(s):
            continue
        out.append(finding(
            "medium", "orphan_state", m["name"],
            f"{s} is written but nothing ever branches on it.",
            f"Rows reach {s} and then no code asks about it. Nothing guards a "
            f"transition out of it, no query filters on it, no report counts it. Either "
            f"it is a write-only label that could be a timestamp instead, or the "
            f"handling that was meant to read it was never written.",
            f"# add the guard that reads {s}, or stop writing a state nothing consumes",
            [s], ev([w for w in m["writes"] if w["state"] == s]),
        ))


def rule_no_terminal(m: dict, out: list) -> None:
    if any(is_terminal(s) for s in m["states"]):
        return
    outgoing = {t["from"] for t in m["transitions"] if t["from"] != "*"}
    if not m["states"] or any(s not in outgoing for s in m["states"]):
        return
    out.append(finding(
        "medium", "no_terminal_state", m["name"],
        "Every state has a way out. The machine never finishes.",
        "A lifecycle with no absorbing state cannot tell you that a thing is done. "
        "Retention, archival, reconciliation and reporting all need a point after "
        "which nothing changes; without one, every row stays live forever and every "
        "query has to carry a date range to pretend otherwise.",
        table_fix(m), [], [],
    ))


def rule_missing_log(m: dict, out: list) -> None:
    if not m["writes"]:
        return
    if any(w.get("logged") or LOG_HINT.search(w.get("snippet") or "") for w in m["writes"]):
        return
    out.append(finding(
        "medium", "missing_transition_log", m["name"],
        f"No transition records when it happened or who caused it.",
        f"{m['field']} holds the current state and nothing else. The moment a dispute "
        f"arrives — why was this refunded, who cancelled it, when did it ship — the "
        f"answer is not in the database. A state column is a cache of the last event; "
        f"if the events are never stored, the history is gone the moment it is "
        f"overwritten.",
        f"ALTER TABLE \"order\" ADD COLUMN {m['field']}_changed_at timestamptz;\n"
        f"-- better: append-only, one row per move\n"
        f"CREATE TABLE {m['field']}_history (\n"
        f"  id bigserial PRIMARY KEY,\n"
        f"  order_id text NOT NULL REFERENCES \"order\" (id),\n"
        f"  from_{m['field']} text,\n"
        f"  to_{m['field']}   text NOT NULL,\n"
        f"  actor_id text,\n"
        f"  reason   text,\n"
        f"  at timestamptz NOT NULL DEFAULT now()\n);",
        [], ev(m["writes"], 3),
    ))


def rule_duplicate_guard(m: dict, out: list) -> None:
    for t in m["transitions"]:
        if len(t["evidence"]) < 2 or t["from"] == "*":
            continue
        files = {e["file"] for e in t["evidence"]}
        if len(files) < 2:
            continue
        out.append(finding(
            "low", "duplicate_guard", m["name"],
            f"{t['from']} -> {t['to']} is implemented in {len(files)} places.",
            "The same rule written twice drifts. One copy gets a new condition, the "
            "other does not, and from then on the behaviour depends on which entry "
            "point the caller used.",
            table_fix(m), [t["from"], t["to"]], ev(t["evidence"]),
        ))


def rule_literal_writes(m: dict, out: list) -> None:
    if m["kind"] in {"sql_check", "sql_enum_column", "sql_enum_type", "const_array", "ts_union"}:
        return
    literals = [
        w for w in m["writes"]
        if m["name"] not in (w.get("snippet") or "") and not w.get("validated")
    ]
    if not literals:
        return
    out.append(finding(
        "low", "literal_state_write", m["name"],
        f"{len(literals)} write(s) use a bare string instead of {m['name']}.",
        f"A typo in a quoted state is a value the compiler accepts and the enum "
        f"rejects only at the database boundary, if at all. Referring to "
        f"{m['name']} by its member name moves that failure to the editor.",
        f"- data: {{ {m['field']}: \"{literals[0]['state']}\" }}\n"
        f"+ data: {{ {m['field']}: {m['name']}.{literals[0]['state'].upper()} }}",
        [], ev(literals, 3),
    ))


RULES = [
    rule_terminal_escape, rule_unconstrained_write, rule_unguarded_write,
    rule_backwards, rule_race, rule_bypass, rule_unreachable, rule_dead_state,
    rule_orphan_state, rule_no_terminal, rule_missing_log,
    rule_duplicate_guard, rule_literal_writes,
]


def audit(doc: dict) -> dict:
    out: list = []
    for m in doc.get("machines", []):
        for rule in RULES:
            rule(m, out)
    out.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["machine"], f["rule"]))
    counts: dict = {}
    for f in out:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    machines = doc.get("machines", [])
    return {
        "source": doc.get("source"),
        "machine_count": len(machines),
        "state_count": sum(len(m["states"]) for m in machines),
        "transition_count": sum(len(m["transitions"]) for m in machines),
        "files_scanned": doc.get("files_scanned"),
        "counts": counts,
        "findings": out,
        "machines": machines,
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def render_text(report: dict, show_fix: bool = True) -> str:
    c = report["counts"]
    total = sum(c.values())
    lines = [
        "",
        f"  STATE AUDIT   {report['source']}",
        f"  {report['machine_count']} machine{plural(report['machine_count'])} · "
        f"{report['state_count']} states · "
        f"{report['transition_count']} transitions · {report['files_scanned']} files",
        "",
    ]
    for m in report.get("machines", []):
        lines.append(
            f"  {m['name']}.{m['field']}  "
            f"({m['kind']}, {m['declared_in']['file']}:{m['declared_in']['line']})"
        )
    if report.get("machines"):
        lines.append("")
    if not total:
        lines += ["  No findings. Every path in this machine is one you declared.", ""]
        return "\n".join(lines)

    widest = max(max(c.values()), 8)
    for sev in ("critical", "high", "medium", "low"):
        n = c.get(sev, 0)
        if not n:
            continue
        bar = "█" * max(1, round(n / widest * 28))
        lines.append(f"  {sev:<9} {n:>3}  {bar}")
    lines += ["", f"  {total} findings across {report['machine_count']} "
                  f"machine{plural(report['machine_count'])}", ""]

    for sev in ("critical", "high", "medium", "low"):
        group = [f for f in report["findings"] if f["severity"] == sev]
        if not group:
            continue
        title = f"{sev.upper()}  ({len(group)})"
        lines += ["", f"  {title}", "  " + "─" * max(len(title), 58)]
        for f in group:
            loc = f["machine"] + (f" · {' -> '.join(f['states'])}" if f["states"] else "")
            lines.append(f"  {loc}")
            lines.append(f"    {f['message']}")
            lines.append(f"    {f['rule']} — {f['why']}")
            for e in f["evidence"]:
                g = f" (guard at :{e['guard_line']})" if e.get("guard_line") else ""
                lines.append(f"      {e['file']}:{e['line']}{g}  {e['snippet']}")
            if show_fix and f["fix"]:
                lines.append("")
                for fl in f["fix"].splitlines():
                    lines.append(f"      {fl}")
            lines.append("")
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    c = report["counts"]
    out = [
        f"# State audit — `{report['source']}`",
        "",
        f"**{report['machine_count']} machine{plural(report['machine_count'])}** · {report['state_count']} states · "
        f"{report['transition_count']} transitions · "
        + " · ".join(
            f"{c[s]} {s}" for s in ("critical", "high", "medium", "low") if c.get(s)
        ),
        "",
        "| Severity | Machine | Rule | Finding | Evidence |",
        "|---|---|---|---|---|",
    ]
    for f in report["findings"]:
        msg = f["message"].replace("|", "\\|")
        eviden = ", ".join(
            f"`{e['file']}:{e['line']}`" for e in f["evidence"][:2]
        ) or "—"
        out.append(
            f"| {f['severity']} | `{f['machine']}` | `{f['rule']}` | {msg} | {eviden} |"
        )
    out += ["", "## Fixes", ""]
    seen = set()
    for f in report["findings"]:
        if not f["fix"] or f["fix"] in seen:
            continue
        seen.add(f["fix"])
        out += [f"### `{f['machine']}` — {f['rule']}", "", f["why"], "",
                "```" + ("sql" if f["fix"].lstrip().upper().startswith(("ALTER", "CREATE")) else ""),
                f["fix"], "```", ""]
    return "\n".join(out)


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if not args:
        print(
            "usage: audit.py <path-to-codebase|machines.json> "
            "[--json|--markdown] [--strict] [--no-fix]",
            file=sys.stderr,
        )
        return 2

    path = args[0]
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    else:
        import extract
        doc = extract.build(path)

    report = audit(doc)
    if "--json" in flags:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif "--markdown" in flags:
        print(render_markdown(report))
    else:
        print(render_text(report, show_fix="--no-fix" not in flags))

    crit = report["counts"].get("critical", 0)
    return 1 if crit and "--strict" in flags else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
