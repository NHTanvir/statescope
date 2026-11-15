#!/usr/bin/env python3
"""Tests for statescope: extraction, every rule, and rendering.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import audit  # noqa: E402
import extract  # noqa: E402
import render  # noqa: E402

EXAMPLES = os.path.join(ROOT, "examples", "order-lifecycle")


def tree(files: dict) -> str:
    """Write a throwaway codebase and return its path."""
    root = tempfile.mkdtemp(prefix="statescope-test-")
    for rel, body in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(body)
    return root


class Base(unittest.TestCase):
    def setUp(self):
        self._dirs = []

    def tearDown(self):
        for d in self._dirs:
            shutil.rmtree(d, ignore_errors=True)

    def build(self, files: dict) -> dict:
        root = tree(files)
        self._dirs.append(root)
        return extract.build(root)

    def one(self, files: dict) -> dict:
        doc = self.build(files)
        self.assertEqual(doc["machine_count"], 1, doc)
        return doc["machines"][0]

    def rules(self, files: dict) -> set:
        doc = self.build(files)
        return {f["rule"] for f in audit.audit(doc)["findings"]}


# --------------------------------------------------------------------------
# state set declarations
# --------------------------------------------------------------------------

class TestDeclarations(Base):
    def test_prisma_enum_and_field_and_default(self):
        m = self.one({
            "schema.prisma": (
                "enum OrderStatus {\n  PENDING\n  PAID\n  SHIPPED\n}\n\n"
                "model Order {\n  id String @id\n"
                "  status OrderStatus @default(PENDING)\n}\n"
            ),
            "a.ts": "o.status = 'paid';\n",
        })
        self.assertEqual(m["kind"], "prisma_enum")
        self.assertEqual(m["field"], "status")
        self.assertEqual(m["initial"], "pending")
        self.assertEqual(m["states"], ["pending", "paid", "shipped"])

    def test_field_is_not_the_enum_keyword(self):
        m = self.one({
            "schema.prisma": "enum TaskStatus {\n  OPEN\n  DONE\n}\n"
                             "model Task {\n  state TaskStatus @default(OPEN)\n}\n",
            "a.ts": "t.state = 'done';\n",
        })
        self.assertEqual(m["field"], "state")

    def test_typescript_union(self):
        m = self.one({
            "types.ts": "export type JobState = 'queued' | 'running' | 'done';\n",
            "job.ts": "job.state = 'running';\n",
        })
        self.assertEqual(m["kind"], "ts_union")
        self.assertEqual(m["states"], ["queued", "running", "done"])

    def test_typescript_enum_uses_values(self):
        m = self.one({
            "s.ts": "export enum Status {\n  Draft = 'draft',\n  Live = 'live',\n}\n",
            "p.ts": "page.status = 'live';\n",
        })
        self.assertEqual(m["states"], ["draft", "live"])

    def test_python_enum(self):
        m = self.one({
            "models.py": (
                "from enum import Enum\n\n"
                "class TicketStatus(str, Enum):\n"
                "    OPEN = 'open'\n    CLOSED = 'closed'\n"
            ),
            "svc.py": "ticket.status = 'closed'\n",
        })
        self.assertEqual(m["kind"], "py_enum")
        self.assertEqual(m["states"], ["open", "closed"])

    def test_php_enum(self):
        m = self.one({
            "Status.php": (
                "<?php\nenum InvoiceStatus: string {\n"
                "    case Draft = 'draft';\n    case Paid = 'paid';\n}\n"
            ),
            "svc.php": "<?php\n$invoice->status = 'paid';\n",
        })
        self.assertEqual(m["kind"], "php_enum")
        self.assertEqual(m["states"], ["draft", "paid"])

    def test_sql_check_constraint(self):
        m = self.one({
            "schema.sql": (
                "CREATE TABLE orders (\n  id int,\n"
                "  status text DEFAULT 'pending'\n"
                "    CHECK (status IN ('pending', 'paid', 'shipped'))\n);\n"
            ),
            "app.py": "order.status = 'paid'\n",
        })
        self.assertEqual(m["kind"], "sql_check")
        self.assertEqual(m["initial"], "pending")

    def test_non_lifecycle_enum_is_ignored(self):
        doc = self.build({
            "schema.prisma": "enum Currency {\n  USD\n  EUR\n  GBP\n}\n",
            "a.ts": "invoice.currency = 'USD';\n",
        })
        self.assertEqual(doc["machine_count"], 0)

    def test_unused_enum_is_ignored(self):
        doc = self.build({"schema.prisma": "enum Status {\n  A\n  B\n}\n"})
        self.assertEqual(doc["machine_count"], 0)


# --------------------------------------------------------------------------
# writes, reads, guards
# --------------------------------------------------------------------------

GUARDED = {
    "schema.prisma": "enum S {\n  PENDING\n  PAID\n  SHIPPED\n}\n"
                     "model O {\n  status S @default(PENDING)\n}\n",
    "svc.ts": (
        "export async function ship(id) {\n"
        "  const o = await get(id);\n"
        "  if (o.status === 'paid') {\n"
        "    await db.o.update({ where: { id }, data: { status: 'shipped' } });\n"
        "  }\n"
        "}\n"
    ),
}


class TestFlow(Base):
    def test_guard_above_write_becomes_an_edge(self):
        m = self.one(GUARDED)
        edges = {(t["from"], t["to"], t["kind"]) for t in m["transitions"]}
        self.assertIn(("paid", "shipped", "guarded"), edges)

    def test_edge_carries_its_evidence(self):
        m = self.one(GUARDED)
        t = next(t for t in m["transitions"] if t["to"] == "shipped")
        e = t["evidence"][0]
        self.assertEqual(e["file"], "svc.ts")
        self.assertEqual(e["line"], 4)
        self.assertEqual(e["guard_line"], 3)

    def test_write_with_no_guard_is_wildcard(self):
        m = self.one({
            "schema.prisma": "enum S {\n  PENDING\n  PAID\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": "export function f(id) {\n"
                      "  db.o.update({ where: { id }, data: { status: 'paid' } });\n}\n",
        })
        self.assertEqual(
            [(t["from"], t["kind"]) for t in m["transitions"]], [("*", "unguarded")]
        )

    def test_comparison_is_not_a_write(self):
        m = self.one({
            "schema.prisma": "enum S {\n  OPEN\n  CLOSED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": "if (o.status === 'closed') { notify(); }\n",
        })
        self.assertEqual(m["writes"], [])
        self.assertEqual(len(m["reads"]), 1)

    def test_comment_is_never_evidence(self):
        m = self.one({
            "schema.prisma": "enum S {\n  OPEN\n  CLOSED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": (
                "// o.status = 'closed' was removed in #412\n"
                "const o = await get(id);\n"
                "if (o.status === 'open') {\n"
                "  await db.o.update({ where: { id }, data: { status: 'closed' } });\n}\n"
            ),
        })
        self.assertEqual([w["line"] for w in m["writes"]], [4])
        self.assertTrue(all(r["line"] != 1 for r in m["reads"]), m["reads"])

    def test_guard_across_a_function_boundary_does_not_count(self):
        m = self.one({
            "schema.prisma": "enum S {\n  PAID\n  SHIPPED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": (
                "function a(o) {\n  if (o.status === 'paid') { return true; }\n}\n"
                "function b(id) {\n"
                "  db.o.update({ where: { id }, data: { status: 'shipped' } });\n}\n"
            ),
        })
        self.assertTrue(all(t["from"] == "*" for t in m["transitions"]), m["transitions"])

    def test_state_in_where_clause_is_race_free(self):
        m = self.one({
            "schema.prisma": "enum S {\n  PAID\n  SHIPPED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": (
                "const o = await get(id);\n"
                "if (o.status === 'paid') {\n"
                "  await db.o.updateMany({ where: { id, status: 'paid' },"
                " data: { status: 'shipped' } });\n}\n"
            ),
        })
        t = next(t for t in m["transitions"] if t["to"] == "shipped")
        self.assertTrue(t["predicate"])

    def test_declared_table_is_read_as_the_machine(self):
        m = self.one({
            "schema.prisma": "enum S {\n  PENDING\n  PAID\n  SHIPPED\n}\n"
                             "model O {\n  status S @default(PENDING)\n}\n",
            "machine.ts": (
                "const ALLOWED = {\n"
                "  PENDING: ['PAID'],\n"
                "  PAID: ['SHIPPED'],\n"
                "  SHIPPED: [],\n};\n"
            ),
        })
        edges = {(t["from"], t["to"]) for t in m["transitions"]}
        self.assertEqual(edges, {("pending", "paid"), ("paid", "shipped")})
        self.assertTrue(all(t["kind"] == "declared" for t in m["transitions"]))

    def test_free_write_of_a_variable_is_detected(self):
        m = self.one({
            "schema.prisma": "enum S {\n  OPEN\n  CLOSED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": "export function set(id, status) {\n"
                      "  db.o.update({ where: { id }, data: { status } });\n}\n",
        })
        self.assertEqual(len(m["free_writes"]), 1)
        self.assertEqual(m["free_writes"][0]["line"], 2)

    def test_type_annotation_is_not_a_free_write(self):
        m = self.one({
            "schema.prisma": "enum S {\n  OPEN\n  CLOSED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": "export function set(id: string, status: string) {\n"
                      "  log(status);\n}\nconst x = { status: 'open' };\n",
        })
        self.assertEqual(m["free_writes"], [])

    def test_validated_free_write_is_not_reported(self):
        rules = self.rules({
            "schema.prisma": "enum S {\n  OPEN\n  CLOSED\n}\nmodel O {\n  status S\n}\n",
            "svc.ts": (
                "const ALLOWED = { OPEN: ['CLOSED'], CLOSED: [] };\n"
                "export function move(id, from, status) {\n"
                "  if (!ALLOWED[from].includes(status)) throw new Error('no');\n"
                "  db.o.updateMany({ where: { id, status: from },"
                " data: { status, statusChangedAt: new Date() } });\n}\n"
            ),
        })
        self.assertNotIn("unconstrained_write", rules)


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def codebase(body: str, states="PENDING\n  PAID\n  SHIPPED\n  REFUNDED") -> dict:
    return {
        "schema.prisma": f"enum S {{\n  {states}\n}}\n"
                         "model O {\n  status S @default(PENDING)\n}\n",
        "svc.ts": body,
    }


class TestRules(Base):
    def test_terminal_state_escape(self):
        self.assertIn("terminal_state_escape", self.rules(codebase(
            "const o = await get(id);\n"
            "if (o.status === 'refunded') {\n"
            "  await db.o.update({ where: { id }, data: { status: 'pending' } });\n}\n"
        )))

    def test_unguarded_write(self):
        self.assertIn("unguarded_write", self.rules(codebase(
            "await db.o.update({ where: { id }, data: { status: 'shipped' } });\n"
        )))

    def test_initial_state_write_is_not_unguarded(self):
        rules = self.rules(codebase(
            "await db.o.create({ data: { status: 'pending' } });\n"
        ))
        self.assertNotIn("unguarded_write", rules)

    def test_backwards_transition(self):
        self.assertIn("backwards_transition", self.rules(codebase(
            "const o = await get(id);\n"
            "if (o.status === 'shipped') {\n"
            "  await db.o.update({ where: { id }, data: { status: 'paid' } });\n}\n"
        )))

    def test_forward_transition_is_not_backwards(self):
        self.assertNotIn("backwards_transition", self.rules(codebase(
            "const o = await get(id);\n"
            "if (o.status === 'paid') {\n"
            "  await db.o.update({ where: { id }, data: { status: 'shipped' } });\n}\n"
        )))

    def test_concurrent_write_race(self):
        self.assertIn("concurrent_write_race", self.rules(codebase(
            "const o = await get(id);\n"
            "if (o.status === 'paid') {\n"
            "  await db.o.update({ where: { id }, data: { status: 'shipped' } });\n}\n"
        )))

    def test_dead_state(self):
        rules = self.rules(codebase(
            "const o = await get(id);\n"
            "if (o.status === 'pending') {\n"
            "  await db.o.updateMany({ where: { id, status: 'pending' },"
            " data: { status: 'paid', statusChangedAt: new Date() } });\n}\n"
        ))
        self.assertIn("dead_state", rules)

    def test_unconstrained_write(self):
        self.assertIn("unconstrained_write", self.rules(codebase(
            "export function set(id, status) {\n"
            "  db.o.update({ where: { id }, data: { status } });\n}\n"
        )))

    def test_missing_transition_log(self):
        self.assertIn("missing_transition_log", self.rules(codebase(
            "await db.o.update({ where: { id }, data: { status: 'shipped' } });\n"
        )))

    def test_logged_transition_is_not_reported(self):
        self.assertNotIn("missing_transition_log", self.rules(codebase(
            "await db.o.update({ where: { id },"
            " data: { status: 'shipped', statusChangedAt: new Date() } });\n"
        )))

    def test_severity_is_ordered_and_counted(self):
        doc = self.build(codebase(
            "const o = await get(id);\n"
            "if (o.status === 'refunded') {\n"
            "  await db.o.update({ where: { id }, data: { status: 'pending' } });\n}\n"
        ))
        report = audit.audit(doc)
        sevs = [f["severity"] for f in report["findings"]]
        self.assertEqual(sevs, sorted(sevs, key=lambda s: audit.SEVERITY_ORDER[s]))
        self.assertEqual(sum(report["counts"].values()), len(report["findings"]))

    def test_every_finding_has_evidence_or_a_declaration(self):
        doc = self.build(codebase(
            "await db.o.update({ where: { id }, data: { status: 'shipped' } });\n"
        ))
        for f in audit.audit(doc)["findings"]:
            self.assertTrue(f["message"] and f["why"], f)
            if f["rule"] != "no_terminal_state":
                self.assertTrue(f["evidence"], f["rule"])


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

class TestRender(Base):
    def setUp(self):
        super().setUp()
        self.doc = extract.build(os.path.join(EXAMPLES, "before"))
        self.report = audit.audit(self.doc)

    def test_mermaid_header_and_edges(self):
        out = render.to_mermaid(self.doc, self.report)
        self.assertTrue(out.startswith("stateDiagram-v2"))
        self.assertIn("refunded --> pending", out)
        self.assertIn("[*] --> pending", out)

    def test_mermaid_labels_never_contain_a_stray_colon(self):
        out = render.to_mermaid(self.doc, self.report)
        for line in out.splitlines():
            if " : " in line:
                self.assertNotIn(":", line.split(" : ", 1)[1], line)

    def test_mermaid_marks_the_bad_states(self):
        out = render.to_mermaid(self.doc, self.report)
        self.assertIn("classDef escape", out)
        self.assertIn("class disputed dead", out)

    def test_html_is_self_contained_and_themed(self):
        out = render.to_html(self.doc, self.report)
        self.assertTrue(out.startswith("<!doctype html>"))
        self.assertIn("prefers-color-scheme: dark", out)
        self.assertIn("stateDiagram-v2", out)
        self.assertIn("terminal_state_escape", out)

    def test_html_escapes_the_findings(self):
        out = render.to_html(self.doc, self.report)
        self.assertNotIn("<script>alert", out)
        self.assertIn("&gt;", out)


# --------------------------------------------------------------------------
# the shipped examples, end to end through the CLI
# --------------------------------------------------------------------------

class TestExamples(unittest.TestCase):
    def run_cli(self, script: str, *args: str):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", script), *args],
            capture_output=True, text=True,
        )
        return proc

    def test_before_example_has_criticals(self):
        proc = self.run_cli("audit.py", os.path.join(EXAMPLES, "before"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertGreaterEqual(report["counts"].get("critical", 0), 5)
        self.assertEqual(report["machine_count"], 1)

    def test_before_example_strict_exits_nonzero(self):
        proc = self.run_cli("audit.py", os.path.join(EXAMPLES, "before"), "--strict")
        self.assertEqual(proc.returncode, 1)

    def test_after_example_is_clean(self):
        proc = self.run_cli("audit.py", os.path.join(EXAMPLES, "after"), "--json")
        report = json.loads(proc.stdout)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["transition_count"], 5)

    def test_after_example_strict_exits_zero(self):
        proc = self.run_cli("audit.py", os.path.join(EXAMPLES, "after"), "--strict")
        self.assertEqual(proc.returncode, 0)

    def test_markdown_output_is_a_table(self):
        proc = self.run_cli("audit.py", os.path.join(EXAMPLES, "before"), "--markdown")
        self.assertIn("| Severity | Machine | Rule | Finding | Evidence |", proc.stdout)

    def test_render_writes_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "report.html")
            proc = self.run_cli(
                "render.py", os.path.join(EXAMPLES, "before"), f"--out={dest}"
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(dest, encoding="utf-8") as fh:
                self.assertIn("stateDiagram-v2", fh.read())

    def test_extract_cli_emits_json(self):
        proc = self.run_cli("extract.py", os.path.join(EXAMPLES, "before"))
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["machines"][0]["name"], "OrderStatus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
