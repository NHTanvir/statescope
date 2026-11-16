#!/usr/bin/env python3
"""Infer the state machine a codebase actually implements.

Reads source files, finds the declared state set (a Prisma enum, a TypeScript
union, a Python Enum, a PHP enum, a SQL CHECK constraint), then finds every
place a state is written and every place one is read in a comparison. A write
preceded by a read of state A is the edge A -> B, cited to the line that allows
it. A write with no such read is the edge * -> B.

Nothing is guessed that is not shown: every edge carries its file and line.
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", "env", ".tox", "coverage", ".cache",
    "target", ".idea", ".vscode", "bower_components", ".svelte-kit", "public",
}
CODE_EXT = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".php", ".rb", ".go",
}
DECL_EXT = CODE_EXT | {".prisma", ".sql"}
MAX_BYTES = 1_500_000

# A state set is only a lifecycle if its name or its members say so. Without
# this filter every Role, Currency and Locale enum becomes a state machine.
FIELD_HINT = re.compile(
    r"(?:^|_)(status|state|stage|phase|step|lifecycle|workflow|condition)s?$", re.I
)
LIFECYCLE_WORDS = {
    "pending", "paid", "unpaid", "shipped", "delivered", "cancelled", "canceled",
    "refunded", "completed", "complete", "failed", "active", "inactive", "draft",
    "published", "archived", "approved", "rejected", "processing", "queued",
    "expired", "suspended", "closed", "open", "new", "created", "confirmed",
    "fulfilled", "returned", "disputed", "settled", "submitted", "in_progress",
    "inprogress", "in_review", "awaiting_payment", "on_hold", "onhold", "void",
    "voided", "revoked", "trialing", "past_due", "deleted", "done", "started",
    "finished", "ready", "running", "stopped", "scheduled", "verified",
}
# States nothing should leave. Leaving one is the finding people screenshot.
TERMINAL_WORDS = {
    "refunded", "cancelled", "canceled", "completed", "complete", "closed",
    "delivered", "failed", "expired", "archived", "deleted", "rejected",
    "fulfilled", "settled", "done", "finished", "terminated", "revoked",
    "void", "voided", "returned",
}
# Only well-known words are ranked. An unranked pair is never called backwards.
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


def norm(state: str) -> str:
    """PENDING, Pending, pending -> pending. Used for comparison only."""
    return re.sub(r"[^a-z0-9]+", "_", (state or "").strip().lower()).strip("_")


def is_terminal(state: str) -> bool:
    return norm(state) in TERMINAL_WORDS


def rank(state: str):
    return RANK.get(norm(state))


# --------------------------------------------------------------------------
# file walking
# --------------------------------------------------------------------------

def walk(root: str) -> list:
    """Return [(relpath, abspath, lines)] for every candidate file."""
    out = []
    if os.path.isfile(root):
        base = os.path.dirname(os.path.abspath(root)) or "."
        files = [(os.path.basename(root), os.path.abspath(root))]
    else:
        base = os.path.abspath(root)
        files = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
            )
            for fn in sorted(filenames):
                if os.path.splitext(fn)[1].lower() in DECL_EXT:
                    full = os.path.join(dirpath, fn)
                    files.append((os.path.relpath(full, base), full))
    for rel, full in files:
        try:
            if os.path.getsize(full) > MAX_BYTES:
                continue
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        out.append((rel.replace(os.sep, "/"), full, lines))
    return out


def strip_comment(line: str) -> str:
    """Remove the obvious trailing comment so comments never become evidence."""
    for marker in ("//", "#", "--"):
        idx = line.find(marker)
        while idx != -1:
            before = line[:idx]
            if before.count("'") % 2 == 0 and before.count('"') % 2 == 0:
                return before
            idx = line.find(marker, idx + 1)
    return line


# --------------------------------------------------------------------------
# state set declarations
# --------------------------------------------------------------------------

RE_PRISMA_ENUM = re.compile(r"^[ \t]*enum\s+(\w+)\s*\{", re.M)
RE_TS_ENUM = re.compile(r"^[ \t]*(?:export\s+)?(?:const\s+)?enum\s+(\w+)\s*\{", re.M)
RE_TS_UNION = re.compile(
    r"^[ \t]*(?:export\s+)?type\s+(\w+)\s*=\s*([^;{}]*?)(?:;|$)", re.M
)
RE_CONST_ARR = re.compile(
    r"^[ \t]*(?:export\s+)?const\s+(\w+)\s*=\s*\[([^\]]*)\]\s*as\s+const", re.M
)
RE_PY_ENUM = re.compile(r"^[ \t]*class\s+(\w+)\s*\(([^)]*)\)\s*:", re.M)
RE_PHP_ENUM = re.compile(r"^[ \t]*enum\s+(\w+)\s*(?::\s*\w+)?\s*\{", re.M)
RE_SQL_CHECK = re.compile(
    r"(?:CONSTRAINT\s+\w+\s+)?CHECK\s*\(\s*\(?\s*[\"'`\[]?(\w+)[\"'`\]]?\s*\)?\s+IN\s*\(([^)]*)\)",
    re.I,
)
RE_SQL_ENUM_COL = re.compile(r"[\"'`]?(\w+)[\"'`]?\s+ENUM\s*\(([^)]*)\)", re.I)
RE_SQL_CREATE_TYPE = re.compile(
    r"CREATE\s+TYPE\s+[\"'`]?(\w+)[\"'`]?\s+AS\s+ENUM\s*\(([^)]*)\)", re.I
)
RE_LITERALS = re.compile(r"""['"]([A-Za-z][\w\- ]{1,40})['"]""")


def _block(lines: list, start: int) -> tuple:
    """Lines of a brace-delimited block opened on line index `start`."""
    depth = 0
    body = []
    for i in range(start, min(len(lines), start + 400)):
        line = lines[i]
        depth += line.count("{") - line.count("}")
        if i > start or "{" in line:
            body.append((i, line))
        if depth <= 0 and i >= start and "{" in "".join(lines[start : i + 1]):
            return body, i
    return body, min(len(lines) - 1, start + 400)


def _py_block(lines: list, start: int) -> tuple:
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = []
    end = start
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            body.append((i, line))
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        body.append((i, line))
        end = i
    return body, end


def declarations(files: list) -> list:
    """Every state set found, before lifecycle filtering."""
    found = []

    def add(kind, name, states, rel, line, field=None):
        clean = []
        for s in states:
            s = s.strip().strip("'\"` ")
            if s and re.match(r"^[A-Za-z][\w\- ]*$", s) and norm(s) not in {n for n, _ in clean}:
                clean.append((norm(s), s))
        if len(clean) >= 2:
            found.append({
                "kind": kind, "name": name, "field": field,
                "states": [{"name": n, "literal": lit} for n, lit in clean],
                "file": rel, "line": line + 1,
                "decl_lines": set(),
            })
            return found[-1]
        return None

    for rel, full, lines in files:
        ext = os.path.splitext(rel)[1].lower()
        text = "\n".join(lines)

        if ext == ".prisma":
            for m in RE_PRISMA_ENUM.finditer(text):
                start = text[: m.start(1)].count("\n")
                body, end = _block(lines, start)
                members = []
                for _, bl in body:
                    bl = strip_comment(bl).strip().rstrip(",")
                    if re.match(r"^[A-Za-z]\w*$", bl):
                        members.append(bl)
                d = add("prisma_enum", m.group(1), members, rel, start)
                if d:
                    d["decl_lines"] = {i for i, _ in body}
                    fm = re.search(
                        r"^[ \t]*(?!enum\b)(\w+)\s+" + re.escape(m.group(1)) + r"\b",
                        text, re.M,
                    )
                    if fm:
                        d["field"] = fm.group(1)
                    dm = re.search(
                        r"^[ \t]*\w+\s+" + re.escape(m.group(1))
                        + r"[^\n]*@default\((\w+)\)", text, re.M,
                    )
                    if dm:
                        d["initial"] = norm(dm.group(1))

        if ext == ".sql":
            for m in RE_SQL_CREATE_TYPE.finditer(text):
                add("sql_enum_type", m.group(1), RE_LITERALS.findall(m.group(2)),
                    rel, text[: m.start(1)].count("\n"))
            for m in RE_SQL_CHECK.finditer(text):
                d = add("sql_check", m.group(1), RE_LITERALS.findall(m.group(2)),
                        rel, text[: m.start(1)].count("\n"), field=m.group(1))
                if d:
                    dm = re.search(
                        re.escape(m.group(1)) + r"[^,;\n]*DEFAULT\s+'([^']+)'",
                        text, re.I,
                    )
                    if dm:
                        d["initial"] = norm(dm.group(1))
            for m in RE_SQL_ENUM_COL.finditer(text):
                add("sql_enum_column", m.group(1), RE_LITERALS.findall(m.group(2)),
                    rel, text[: m.start(1)].count("\n"), field=m.group(1))

        if ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
            for m in RE_TS_ENUM.finditer(text):
                start = text[: m.start(1)].count("\n")
                body, _ = _block(lines, start)
                vals, keys = [], []
                for _, bl in body:
                    em = re.match(r"\s*(\w+)\s*=\s*['\"]([^'\"]+)['\"]", bl)
                    if em:
                        keys.append(em.group(1))
                        vals.append(em.group(2))
                    else:
                        km = re.match(r"\s*(\w+)\s*,?\s*$", strip_comment(bl))
                        if km and km.group(1) not in {"export", "const", "enum"}:
                            keys.append(km.group(1))
                d = add("ts_enum", m.group(1), vals or keys, rel, start)
                if d:
                    d["decl_lines"] = {i for i, _ in body}
                    d["members"] = keys
            for m in RE_TS_UNION.finditer(text):
                lits = RE_LITERALS.findall(m.group(2))
                if lits and "|" in m.group(2):
                    d = add("ts_union", m.group(1), lits, rel,
                            text[: m.start(1)].count("\n"))
                    if d:
                        d["decl_lines"] = {
                            text[: m.start(1)].count("\n") + k
                            for k in range(m.group(0).count("\n") + 1)
                        }
            for m in RE_CONST_ARR.finditer(text):
                d = add("const_array", m.group(1), RE_LITERALS.findall(m.group(2)),
                        rel, text[: m.start(1)].count("\n"))
                if d:
                    d["decl_lines"] = {
                        text[: m.start(1)].count("\n") + k
                        for k in range(m.group(0).count("\n") + 1)
                    }

        if ext == ".py":
            for m in RE_PY_ENUM.finditer(text):
                if "enum" not in m.group(2).lower():
                    continue
                start = text[: m.start(1)].count("\n")
                body, _ = _py_block(lines, start)
                vals, keys = [], []
                for _, bl in body:
                    em = re.match(r"\s*(\w+)\s*[:=]\s*['\"]([^'\"]+)['\"]", bl)
                    if em:
                        keys.append(em.group(1))
                        vals.append(em.group(2))
                    elif re.match(r"\s*(\w+)\s*=\s*auto\(\)", bl):
                        keys.append(re.match(r"\s*(\w+)", bl).group(1))
                d = add("py_enum", m.group(1), vals or keys, rel, start)
                if d:
                    d["decl_lines"] = {i for i, _ in body}
                    d["members"] = keys

        if ext == ".php":
            for m in RE_PHP_ENUM.finditer(text):
                start = text[: m.start(1)].count("\n")
                body, _ = _block(lines, start)
                vals, keys = [], []
                for _, bl in body:
                    em = re.match(r"\s*case\s+(\w+)\s*=\s*['\"]([^'\"]+)['\"]", bl)
                    if em:
                        keys.append(em.group(1))
                        vals.append(em.group(2))
                    else:
                        km = re.match(r"\s*case\s+(\w+)\s*;", bl)
                        if km:
                            keys.append(km.group(1))
                d = add("php_enum", m.group(1), vals or keys, rel, start)
                if d:
                    d["decl_lines"] = {i for i, _ in body}
                    d["members"] = keys

    return found


# --------------------------------------------------------------------------
# writes and reads
# --------------------------------------------------------------------------

BOUNDARY = re.compile(
    r"^[ \t]*(?:(?:export\s+)?(?:async\s+)?function\s|def\s|class\s|"
    r"(?:public|private|protected|static)[\w\s]*function\s|"
    r"(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\()"
)
MUTATOR = re.compile(
    r"\b(save|update|updateOne|updateMany|findOneAndUpdate|create|insert|"
    r"execute|commit|persist|flush|write|set|put|patch)\b", re.I
)
LOCK = re.compile(
    r"\bfor\s+update\b|\bwith_lock\b|\block_?for_?update\b|"
    r"\bselect_for_update\b|\bcompare_and_set\b|\bversion\s*:\s*\w", re.I
)


def _predicate(line: str, field) -> bool:
    """True when the state is part of the WHERE clause, not just read into memory.

    `update({ where: { id }, data: { status: 'paid' } })` reads the state into a
    variable and hopes nothing else moved it. `where: { id, status: 'pending' }`
    makes the database refuse a second concurrent caller. Only the second one is
    race-free, so only the second one counts here: the field has to appear inside
    the where clause itself, not anywhere on the line.
    """
    if LOCK.search(line):
        return True
    if not field:
        return False
    m = re.search(r"\b(where|filter)\b", line, re.I)
    if not m:
        return False
    tail = line[m.end():]
    cut = min(
        [i for i in (tail.find("}"), tail.find(")")) if i != -1] or [len(tail)]
    )
    return bool(re.search(r"\b" + re.escape(str(field)) + r"\b", tail[:cut], re.I))
# A write inside the one function that owns the rules is not an unguarded write.
VALIDATION = re.compile(
    r"\bALLOWED\b|\bTRANSITIONS?\b|\bLEGAL\b|\bVALID\w*\b|\bNEXT_STATES?\b|"
    r"\.includes\s*\(|\bin_array\s*\(|\bhas\s*\(|\bObject\.values\s*\(|"
    r"\bcanTransition\b|\bcan_transition\b|\bassertTransition\b|\bz\.enum\b|"
    r"\bIllegalTransition\b|\bguard\w*\s*\(", re.I
)
# The declared machine: a table that says, in one place, which moves are legal.
TABLE_NAME = re.compile(
    r"\b(ALLOWED\w*|TRANSITIONS?\w*|LEGAL\w*|VALID_\w+|NEXT_\w+|STATE_MAP|"
    r"STATE_GRAPH|MACHINE|WORKFLOW)\b"
)

HELPER_NAME = re.compile(
    r"\b(transition|transitionTo|changeStatus|setStatus|updateStatus|markAs|"
    r"moveTo|advance|applyTransition|can_transition|canTransition)\w*", re.I
)


def _field_ok(key: str, field) -> bool:
    if not key:
        return False
    if field and norm(key) == norm(field):
        return True
    return bool(FIELD_HINT.search(key))


# --------------------------------------------------------------------------
# context: is this occurrence selecting rows, or changing them?
# --------------------------------------------------------------------------

_PRED_BRACE = re.compile(
    r"\b(?:where|filter|having|conditions?|query|match|find\w*|count\w*|exists)\s*[:(=]?\s*$", re.I
)
_PRED_PAREN = re.compile(
    r"\b(?:filter|filter_by|exclude|where|get|get_or_none|having|Q|find\w*|count|exists)\s*$", re.I
)
_WRITE_CONTAINER = re.compile(
    r"\b(?:data|set|\$set|values|defaults|create\w*|update\w*|insert\w*|save|upsert|"
    r"attributes|fill)\s*[:(=]?\s*$", re.I
)


def _in_predicate(lines: list, idx: int, line: str, pos: int) -> bool:
    """True when the text at `pos` sits inside a where / filter clause.

    `where: { id, status: 'PAID' }` selects rows in the state `paid`; it does not
    put anything into the column. Reading it as a write reports the race-free
    form of an update as an unguarded write of the state it was protecting.
    """
    before_line = line[:pos]
    # raw SQL on one line: ... WHERE id = 1 AND status = 'paid'
    w = list(re.finditer(r"\bwhere\b(?!\s*[:(])", before_line, re.I))
    if w and not re.search(r"\bset\b", before_line[w[-1].end():], re.I):
        return True

    text = "\n".join(strip_comment(l) for l in lines[max(0, idx - 12):idx]) + "\n" + before_line
    closers = {")": "(", "}": "{", "]": "["}
    depth = {"(": 0, "{": 0, "[": 0}
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch in closers:
            depth[closers[ch]] += 1
        elif ch in depth:
            if depth[ch] > 0:
                depth[ch] -= 1
                continue
            head = text[:i].rstrip()
            if ch == "{" or ch == "[":
                head_tail = head[-40:]
                if _WRITE_CONTAINER.search(head_tail):
                    return False
                if _PRED_BRACE.search(head_tail):
                    return True
            elif ch == "(":
                head_tail = head[-40:]
                if _WRITE_CONTAINER.search(head_tail):
                    return False
                if _PRED_PAREN.search(head_tail):
                    return True
    return False


def _write_patterns(literal: str, member_refs: list) -> list:
    """Regexes that mean 'this line puts the state into a field'."""
    lit = re.escape(literal)
    forms = [r"['\"]" + lit + r"['\"]"]
    forms += [re.escape(r) for r in member_refs]
    val = "(?:" + "|".join(forms) + ")"
    return [
        # x.status = 'paid'   |  $x->status = 'paid'  |  status = 'paid'
        re.compile(r"(?:^|[^=!<>])(?:\$?[\w\.\[\]'\"$>-]*?)\b(\w+)\s*=\s*" + val + r"\s*[;,)\n]?", re.I),
        # status: 'paid'  |  'status' => 'paid'
        re.compile(r"['\"]?(\w+)['\"]?\s*(?::|=>)\s*" + val, re.I),
        # setStatus('paid')  |  set_status('paid')
        re.compile(r"\bset_?(\w+?)\s*\(\s*" + val, re.I),
        # status=STATE  (python kwarg)
        re.compile(r"\b(\w+)\s*=\s*" + val, re.I),
    ]


def _read_patterns(literal: str, member_refs: list) -> list:
    lit = re.escape(literal)
    forms = [r"['\"]" + lit + r"['\"]"]
    forms += [re.escape(r) for r in member_refs]
    val = "(?:" + "|".join(forms) + ")"
    return [
        re.compile(r"(\w+)\s*(?:===|==|!==|!=)\s*" + val, re.I),
        re.compile(val + r"\s*(?:===|==|!==|!=)\s*(?:\$?[\w\.\[\]>-]*?)\b(\w+)\b", re.I),
        re.compile(r"\bcase\s+" + val + r"\s*:?", re.I),
        re.compile(r"\b(\w+)\s+in\s*[\(\[][^\)\]]*" + val, re.I),
        re.compile(r"in_array\s*\(\s*\$?[\w\.\[\]>-]*?\b(\w+)\b[^,]*,\s*\[[^\]]*" + val, re.I),
        re.compile(r"\b(\w+)\s*,\s*" + val, re.I),  # where('status', 'paid')
    ]


def free_writes(files: list, field: str, states: set, enum_name: str) -> list:
    """Writes that put an unconstrained value into the state field.

    `update({ data: { status } })` accepts whatever the caller passed. The enum
    constrains the column, not the call, so every value the application can
    invent reaches the database as long as it is spelled like a member.
    """
    if not field:
        return []
    f = re.escape(field)
    pats = [
        re.compile(r"['\"]?" + f + r"['\"]?\s*(?::|=>)\s*(?!['\"])([A-Za-z_$][\w$\.\[\]'\"-]*)", re.I),
        re.compile(r"[\{,]\s*" + f + r"\s*[,\}]", re.I),
        re.compile(r"(?:^|[^=!<>])\$?[\w\.\[\]>-]*\b" + f + r"\s*=\s*(?!['\"])(\$?[A-Za-z_][\w$\.\[\]>-]*)\s*[;,)]", re.I),
    ]
    out = []
    for rel, _full, lines in files:
        if os.path.splitext(rel)[1].lower() not in CODE_EXT:
            continue
        for idx, raw in enumerate(lines):
            line = strip_comment(raw)
            if not line.strip() or field.lower() not in line.lower():
                continue
            if re.search(r"===|!==|==|!=|\bcase\b|\bif\b|\breturn\b", line):
                continue
            # a parameter list or a type annotation is a declaration, not a write
            if BOUNDARY.match(line) or re.search(
                r"\b(function|def|fn|interface|type)\b", line
            ):
                continue
            for pat in pats:
                m = pat.search(line)
                if not m:
                    continue
                val = (m.group(1) if m.groups() else field).strip()
                if norm(val) in states or enum_name in val:
                    break
                if re.match(
                    r"^(true|false|null|none|nil|undefined|0|1|string|number|bool|"
                    r"boolean|str|int|float|any|unknown|self|this)$", val, re.I
                ):
                    break
                out.append({
                    "file": rel, "line": idx + 1, "value": val,
                    "snippet": line.strip()[:160],
                })
                break
    return out


def scan(files: list, decl: dict) -> None:
    """Fill decl with writes, reads and helpers."""
    field = decl.get("field")
    states = decl["states"]
    enum_name = decl["name"]
    members = decl.get("members") or [s["literal"] for s in states]

    writes, reads, helpers = [], [], []
    for rel, _full, lines in files:
        if os.path.splitext(rel)[1].lower() not in CODE_EXT:
            continue
        decl_here = decl["decl_lines"] if rel == decl["file"] else set()
        for state in states:
            refs = [
                f"{enum_name}.{m}" for m in members if norm(m) == state["name"]
            ] + [
                f"{enum_name}::{m}" for m in members if norm(m) == state["name"]
            ] + [
                f"{enum_name}.{m}.value" for m in members if norm(m) == state["name"]
            ]
            wpats = _write_patterns(state["literal"], refs)
            rpats = _read_patterns(state["literal"], refs)
            for idx, raw in enumerate(lines):
                if idx in decl_here:
                    continue
                line = strip_comment(raw)
                if not line.strip():
                    continue
                low = line.lower()
                if state["literal"].lower() not in low and not any(
                    r.lower() in low for r in refs
                ):
                    continue

                hit_read = None
                for rp in rpats:
                    m = rp.search(line)
                    if m:
                        key = m.group(1) if m.groups() else None
                        if key is None or _field_ok(key, field) or "case" in low:
                            hit_read = (key or field or "state")
                            break
                if hit_read:
                    reads.append({
                        "state": state["name"], "file": rel, "line": idx + 1,
                        "snippet": line.strip()[:160],
                        "predicate": _predicate(line, field),
                    })
                    continue

                write_hit, query_hit = None, None
                for wp in wpats:
                    for m in wp.finditer(line):
                        key = m.group(1) if m.groups() else None
                        if not _field_ok(key, field):
                            continue
                        pos = m.start(1) if m.groups() else m.start()
                        if _in_predicate(lines, idx, line, pos):
                            query_hit = query_hit or key
                        elif write_hit is None:
                            write_hit = key
                    if write_hit is not None:
                        break
                if write_hit is not None:
                    writes.append({
                        "state": state["name"], "file": rel, "line": idx + 1,
                        "snippet": line.strip()[:160],
                        "field": write_hit,
                        "creates": bool(re.search(r"\b(create|insert|new|register|signup)\b", line, re.I)),
                        "predicate": _predicate(line, field),
                    })
                elif query_hit is not None:
                    # selecting rows BY a state is a read of it, and the strongest
                    # kind: the database does the comparing
                    reads.append({
                        "state": state["name"], "file": rel, "line": idx + 1,
                        "snippet": line.strip()[:160],
                        "predicate": True,
                    })

        for idx, raw in enumerate(lines):
            m = HELPER_NAME.search(raw)
            if m and re.search(r"\b(function|def|=>|fn)\b", raw):
                helpers.append({"name": m.group(0), "file": rel, "line": idx + 1})

    decl["writes"] = writes
    decl["reads"] = reads
    decl["helpers"] = helpers
    if not decl.get("field"):
        keys = [w["field"] for w in writes if w.get("field")]
        if keys:
            decl["field"] = max(set(keys), key=keys.count)


def _clean_state(token: str, enum_name: str) -> str:
    """OrderStatus.PENDING, OrderStatus::Pending->value, 'pending' -> pending."""
    t = (token or "").strip().strip("'\"`,[] ")
    t = re.sub(r"->value$|\.value$", "", t)
    t = re.sub(r"^" + re.escape(enum_name) + r"(?:\.|::)", "", t)
    t = re.sub(r"^\w+(?:\.|::)", "", t) if (("." in t) or ("::" in t)) else t
    return norm(t)


def table_edges(files: list, decl: dict) -> list:
    """Transitions declared in a table, rather than inferred from scattered writes.

    A codebase that keeps one allow-list has told you what the machine is. Those
    edges are read from the table and marked `declared`, so the picture matches
    the thing that enforces it instead of the places that bypass it.
    """
    known = {s["name"] for s in decl["states"]}
    enum_name = decl["name"]
    edges = []
    for rel, _full, lines in files:
        if os.path.splitext(rel)[1].lower() not in CODE_EXT:
            continue
        for idx, raw in enumerate(lines):
            if not TABLE_NAME.search(raw) or not re.search(r"[=:]\s*[\{\[]", raw):
                continue
            body, _end = _block(lines, idx) if "{" in raw else ([], idx)
            if not body:
                depth, body = 0, []
                for j in range(idx, min(len(lines), idx + 200)):
                    depth += lines[j].count("[") - lines[j].count("]")
                    body.append((j, lines[j]))
                    if depth <= 0 and j > idx:
                        break
            for j, bl in body:
                line = strip_comment(bl)
                m = re.match(
                    r"\s*\[?\s*([\w'\"`:.>-]+?)\s*(?::|=>)\s*\[([^\]]*)\]", line
                )
                if not m:
                    continue
                src = _clean_state(m.group(1), enum_name)
                if src not in known:
                    continue
                for tok in m.group(2).split(","):
                    dst = _clean_state(tok, enum_name)
                    if dst in known and dst != src:
                        edges.append({
                            "from": src, "to": dst, "kind": "declared",
                            "predicate": True,
                            "evidence": [{
                                "file": rel, "line": j + 1, "guard_line": None,
                                "snippet": line.strip()[:160], "guard": None,
                            }],
                        })
    return edges


def validated(write: dict, files_by_rel: dict, window: int = 30) -> bool:
    """True when an allow-list check dominates this write."""
    lines = files_by_rel.get(write["file"]) or []
    wline = write["line"] - 1
    if wline >= len(lines):
        return False
    windent = len(lines[wline]) - len(lines[wline].lstrip())
    for i in range(max(0, wline - window), wline):
        li = lines[i]
        if not li.strip():
            continue
        if VALIDATION.search(strip_comment(li)):
            crossed = False
            for k in range(i + 1, wline):
                lk = lines[k]
                if lk.strip() and BOUNDARY.match(lk) and (len(lk) - len(lk.lstrip())) < windent:
                    crossed = True
                    break
            if not crossed:
                return True
    return False


def guards_for(write: dict, files_by_rel: dict, reads: list, window: int = 30) -> list:
    """States read in a comparison that dominates this write, with evidence."""
    lines = files_by_rel.get(write["file"]) or []
    wline = write["line"] - 1
    if wline >= len(lines):
        return []
    windent = len(lines[wline]) - len(lines[wline].lstrip())
    found, seen = [], set()
    for r in reads:
        if r["file"] != write["file"]:
            continue
        rline = r["line"] - 1
        if not (0 <= wline - rline <= window):
            continue
        crossed = False
        for i in range(rline + 1, wline):
            li = lines[i]
            if not li.strip():
                continue
            if BOUNDARY.match(li) and (len(li) - len(li.lstrip())) < windent:
                crossed = True
                break
        if crossed:
            continue
        key = (r["state"], r["line"])
        if key in seen:
            continue
        seen.add(key)
        found.append(r)
    return found


def build(root: str) -> dict:
    files = walk(root)
    files_by_rel = {rel: lines for rel, _f, lines in files}
    machines = []

    for decl in declarations(files):
        scan(files, decl)
        name_hint = bool(FIELD_HINT.search(decl["name"])) or (
            decl.get("field") and bool(FIELD_HINT.search(decl["field"]))
        )
        member_hint = sum(
            1 for s in decl["states"] if s["name"] in LIFECYCLE_WORDS
        ) >= 2
        if not (name_hint or member_hint):
            continue
        declared = table_edges(files, decl)
        free = [
            f for f in free_writes(
                files, decl.get("field"),
                {s["name"] for s in decl["states"]}, decl["name"],
            )
            if not validated(f, files_by_rel)
        ]
        # A declared table is on its own proof the machine is real. So is an
        # unconstrained write: a codebase whose only state handling is
        # `data: { status }` is the worst case, not a reason to say nothing.
        if not (decl["writes"] or decl["reads"] or declared or free):
            continue

        transitions = {}
        for e in declared:
            key = (e["from"], e["to"])
            t = transitions.setdefault(key, e)
            if t is not e:
                t["evidence"].extend(e["evidence"])
        for w in decl["writes"]:
            w["validated"] = validated(w, files_by_rel)
            gs = guards_for(w, files_by_rel, decl["reads"])
            if gs:
                for g in gs:
                    if g["state"] == w["state"]:
                        continue
                    key = (g["state"], w["state"])
                    t = transitions.setdefault(key, {
                        "from": g["state"], "to": w["state"], "kind": "guarded",
                        "evidence": [], "predicate": False,
                    })
                    t["evidence"].append({
                        "file": w["file"], "line": w["line"],
                        "guard_line": g["line"], "snippet": w["snippet"],
                        "guard": g["snippet"],
                    })
                    t["predicate"] = t["predicate"] or g.get("predicate") or w.get("predicate")
                w["guarded"] = True
            elif w.get("validated"):
                w["guarded"] = False
            else:
                w["guarded"] = False
                key = ("*", w["state"])
                t = transitions.setdefault(key, {
                    "from": "*", "to": w["state"], "kind": "unguarded",
                    "evidence": [], "predicate": False,
                })
                t["evidence"].append({
                    "file": w["file"], "line": w["line"],
                    "guard_line": None, "snippet": w["snippet"], "guard": None,
                })

        initial = decl.get("initial")
        if not initial:
            creators = [w["state"] for w in decl["writes"] if w.get("creates")]
            if creators:
                initial = creators[0]
            elif decl["states"]:
                ranked = [
                    s["name"] for s in decl["states"] if rank(s["name"]) is not None
                ]
                initial = min(ranked, key=lambda s: rank(s)) if ranked else None

        machines.append({
            "name": decl["name"],
            "kind": decl["kind"],
            "field": decl.get("field") or "status",
            "declared_in": {"file": decl["file"], "line": decl["line"]},
            "states": [s["name"] for s in decl["states"]],
            "literals": {s["name"]: s["literal"] for s in decl["states"]},
            "initial": initial,
            "transitions": sorted(
                transitions.values(), key=lambda t: (t["from"], t["to"])
            ),
            "writes": decl["writes"],
            "reads": decl["reads"],
            "helpers": decl["helpers"],
            "free_writes": free,
        })

    machines.sort(key=lambda m: (-len(m["transitions"]), m["name"]))
    return {
        "source": root,
        "files_scanned": len(files),
        "machine_count": len(machines),
        "machines": machines,
    }


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: extract.py <path-to-codebase-or-file> [--json]", file=sys.stderr)
        return 2
    doc = build(args[0])
    json.dump(doc, sys.stdout, indent=2, default=list)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
