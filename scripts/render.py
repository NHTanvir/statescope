#!/usr/bin/env python3
"""Draw the inferred state machine.

`--mermaid` emits a stateDiagram-v2 that GitHub renders inline, so the machine
can live in a README with no image and no build step. Otherwise this writes one
self-contained HTML file holding the diagram and every finding.

Standard library only.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ANY = "any_state"


def ident(name: str) -> str:
    out = re.sub(r"[^0-9A-Za-z_]", "_", name or "")
    if not out or out[0].isdigit():
        out = "s_" + out
    return out


def label(text: str) -> str:
    """Mermaid transition labels run to end of line: keep them boring."""
    text = re.sub(r"[:;{}|\"#\[\]]", "·", text or "")
    return re.sub(r"\s+", " ", text).strip()


def where(evidence: list) -> str:
    if not evidence:
        return ""
    e = evidence[0]
    base = os.path.basename(str(e.get("file") or ""))
    more = f" +{len(evidence) - 1}" if len(evidence) > 1 else ""
    return f"{base} L{e.get('line')}{more}"


def classify(machine: dict, findings: list) -> dict:
    """Map each state to the one class that matters most for the picture."""
    by_state: dict = {}
    order = {"escape": 0, "open": 1, "dead": 2}

    def mark(state, cls):
        if state in (None, "*", ANY):
            return
        if state not in by_state or order[cls] < order[by_state[state]]:
            by_state[state] = cls

    for f in findings:
        if f["rule"] == "terminal_state_escape" and f["states"]:
            mark(f["states"][0], "escape")
        elif f["rule"] == "backwards_transition" and f["states"]:
            mark(f["states"][0], "escape")
        elif f["rule"] == "unguarded_write" and f["states"]:
            mark(f["states"][0], "open")
        elif f["rule"] in {"dead_state", "unreachable_state"} and f["states"]:
            mark(f["states"][0], "dead")
    return by_state


def to_mermaid(doc: dict, report: dict | None = None, machine: dict | None = None) -> str:
    machines = doc.get("machines") or []
    m = machine or (machines[0] if machines else None)
    if not m:
        return "stateDiagram-v2\n    [*] --> no_state_machine_found"

    findings = [
        f for f in (report or {}).get("findings", []) if f["machine"] == m["name"]
    ]
    cls = classify(m, findings)
    bad_edges = {
        (f["states"][0], f["states"][1]): f["rule"]
        for f in findings
        if f["rule"] in {"terminal_state_escape", "backwards_transition"}
        and len(f["states"]) == 2
    }
    terminal_like = {
        f["states"][0] for f in findings if f["rule"] == "terminal_state_escape"
    }

    lines = ["stateDiagram-v2"]
    lines.append("    direction LR")
    for s in m["states"]:
        lit = (m.get("literals") or {}).get(s, s)
        if lit != s:
            lines.append(f'    state "{label(lit)}" as {ident(s)}')
    if m.get("initial"):
        lines.append(f"    [*] --> {ident(m['initial'])}")

    has_any = any(t["from"] == "*" for t in m["transitions"])
    if has_any:
        lines.append(f'    state "any state" as {ANY}')

    outgoing = {t["from"] for t in m["transitions"]}
    for t in m["transitions"]:
        src = ANY if t["from"] == "*" else ident(t["from"])
        dst = ident(t["to"])
        tag = bad_edges.get((t["from"], t["to"]))
        if t["kind"] == "unguarded":
            text = f"unguarded · {where(t['evidence'])}"
        elif tag == "terminal_state_escape":
            text = f"escapes {t['from']} · {where(t['evidence'])}"
        elif tag == "backwards_transition":
            text = f"backwards · {where(t['evidence'])}"
        else:
            text = where(t["evidence"])
        lines.append(f"    {src} --> {dst}" + (f" : {label(text)}" if text else ""))

    for s in m["states"]:
        if s in terminal_like or (s not in outgoing and s in cls and cls[s] != "dead"):
            lines.append(f"    {ident(s)} --> [*]")
        elif s not in outgoing and s not in cls:
            lines.append(f"    {ident(s)} --> [*]")

    groups: dict = {}
    for s, c in cls.items():
        groups.setdefault(c, []).append(ident(s))
    if groups:
        lines.append("")
        lines.append("    classDef escape fill:#fee2e2,stroke:#dc2626,color:#7f1d1d")
        lines.append("    classDef open fill:#ffedd5,stroke:#ea580c,color:#7c2d12")
        lines.append("    classDef dead fill:#f1f5f9,stroke:#94a3b8,color:#475569")
        for c, names in sorted(groups.items()):
            lines.append(f"    class {','.join(sorted(names))} {c}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_SEV_META = [
    ("critical", "#dc2626"),
    ("high", "#ea580c"),
    ("medium", "#ca8a04"),
    ("low", "#0891b2"),
]

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #ffffff; --panel: #f6f7f9; --border: #dfe3e8;
    --fg: #14171a; --muted: #5b6672; --accent: #2563eb; --code: #f0f2f5;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0f1216; --panel: #161b21; --border: #262d36;
      --fg: #e6e9ed; --muted: #9aa4b0; --accent: #60a5fa; --code: #10141a;
    }
  }
  :root[data-theme="dark"] {
    --bg: #0f1216; --panel: #161b21; --border: #262d36;
    --fg: #e6e9ed; --muted: #9aa4b0; --accent: #60a5fa; --code: #10141a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  header { padding: 28px 16px 20px; border-bottom: 1px solid var(--border); }
  .wrap { max-width: 1240px; margin: 0 auto; }
  h1 { margin: 0 0 6px; font-size: 20px; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: 13px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .bars { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 18px; }
  .bar { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .bar b { font-variant-numeric: tabular-nums; }
  main { max-width: 1240px; margin: 0 auto; padding: 0 16px 64px; }
  .grid { display: grid; grid-template-columns: minmax(0,1.15fr) minmax(0,1fr); gap: 24px; margin-top: 24px; }
  @media (max-width: 960px) { .grid { grid-template-columns: 1fr; } }
  section > h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 12px; font-weight: 600;
  }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .diagram { overflow: auto; }
  .diagram svg { max-width: 100%; height: auto; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 12px; font-size: 12px; color: var(--muted); }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; }
  details { border: 1px solid var(--border); border-radius: 8px; background: var(--panel); margin-bottom: 8px; }
  details[open] { background: var(--bg); }
  summary { cursor: pointer; padding: 10px 12px; display: flex; gap: 10px; align-items: baseline; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  .tag {
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 2px 6px; border-radius: 4px; color: #fff; flex: none;
  }
  .loc { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
  .msg { color: var(--muted); font-size: 13px; }
  .body { padding: 0 12px 12px; }
  .why { font-size: 13.5px; margin: 2px 0 10px; }
  .where { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); margin-bottom: 8px; }
  .where div { padding: 2px 0; }
  pre {
    background: var(--code); border: 1px solid var(--border); border-radius: 6px;
    padding: 10px 12px; overflow: auto; margin: 0;
    font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .rule { font-family: ui-monospace, monospace; font-size: 11.5px; color: var(--muted); margin-top: 8px; }
  footer { max-width: 1240px; margin: 0 auto; padding: 0 16px 48px; color: var(--muted); font-size: 12.5px; }
  footer a { color: var(--accent); }
  .empty { color: var(--muted); font-size: 14px; }
</style>
</head>
<body>
<header><div class="wrap">
  <h1>__HEADING__</h1>
  <div class="sub">__SOURCE__ · __STATES__ states · __TRANSITIONS__ transitions</div>
  <div class="bars">__BARS__</div>
</div></header>
<main>
  <div class="grid">
    <section>
      <h2>__MACHINE__</h2>
      <div class="card diagram"><pre class="mermaid">__MERMAID__</pre></div>
      <div class="legend">
        <span><span class="swatch" style="background:#fee2e2;border:1px solid #dc2626"></span>leaves a terminal state or moves backwards</span>
        <span><span class="swatch" style="background:#ffedd5;border:1px solid #ea580c"></span>reachable with no guard</span>
        <span><span class="swatch" style="background:#f1f5f9;border:1px solid #94a3b8"></span>declared, never written</span>
      </div>
    </section>
    <section>
      <h2>Findings</h2>
      __FINDINGS__
    </section>
  </div>
</main>
<footer>
  Generated by <a href="https://github.com/NHTanvir/statescope">statescope</a>.
  Every edge is cited to the line that allows it. A finding is a judgement, not a fact.
</footer>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs";
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({
    startOnLoad: true,
    theme: dark ? "dark" : "default",
    state: { useMaxWidth: true },
  });
</script>
</body>
</html>
"""


def to_html(doc: dict, report: dict | None = None, title: str | None = None) -> str:
    counts = (report or {}).get("counts", {})
    total = sum(counts.values())
    machines = doc.get("machines") or []
    m = machines[0] if machines else None

    bars = []
    for sev, color in _SEV_META:
        n = counts.get(sev, 0)
        if n:
            bars.append(
                f'<span class="bar"><span class="dot" style="background:{color}">'
                f"</span><b>{n}</b> {sev}</span>"
            )
    if not bars:
        bars.append('<span class="bar">No findings</span>')

    blocks = []
    if report and total:
        colors = dict(_SEV_META)
        for sev, _ in _SEV_META:
            for f in report["findings"]:
                if f["severity"] != sev:
                    continue
                loc = f["machine"]
                if f["states"]:
                    loc += " · " + " → ".join(f["states"])
                wh = "".join(
                    f"<div>{html.escape(str(e['file']))}:{e['line']}"
                    + (f" (guard at :{e['guard_line']})" if e.get("guard_line") else "")
                    + f"  {html.escape(str(e.get('snippet') or ''))}</div>"
                    for e in f["evidence"]
                )
                blocks.append(
                    "<details>"
                    f'<summary><span class="tag" style="background:{colors[sev]}">{sev}</span>'
                    f'<span class="loc">{html.escape(loc)}</span>'
                    f'<span class="msg">{html.escape(f["message"])}</span></summary>'
                    f'<div class="body"><div class="why">{html.escape(f["why"])}</div>'
                    f'<div class="where">{wh}</div>'
                    + (f"<pre>{html.escape(f['fix'])}</pre>" if f.get("fix") else "")
                    + f'<div class="rule">{html.escape(f["rule"])}</div></div>'
                    "</details>"
                )
    else:
        blocks.append(
            '<p class="empty">No findings. Every path in this machine is one you '
            "declared.</p>"
        )

    heading = title or "State review"
    out = HTML_TEMPLATE
    for needle, value in (
        ("__TITLE__", html.escape(f"{heading} — {os.path.basename(str(doc.get('source')))}")),
        ("__HEADING__", html.escape(heading)),
        ("__SOURCE__", html.escape(str(doc.get("source")))),
        ("__STATES__", str(sum(len(x["states"]) for x in machines))),
        ("__TRANSITIONS__", str(sum(len(x["transitions"]) for x in machines))),
        ("__MACHINE__", html.escape(f"{m['name']}.{m['field']}" if m else "No machine found")),
        ("__MERMAID__", html.escape(to_mermaid(doc, report))),
        ("__BARS__", "".join(bars)),
        ("__FINDINGS__", "".join(blocks)),
    ):
        out = out.replace(needle, value)
    return out


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {
        a.split("=")[0]: (a.split("=", 1)[1] if "=" in a else True)
        for a in argv[1:] if a.startswith("--")
    }
    if not args:
        print(
            "usage: render.py <path-to-codebase|machines.json> "
            "[--mermaid] [--out=FILE] [--machine=NAME]",
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

    import audit as audit_mod
    report = audit_mod.audit(doc)

    want = flags.get("--machine")
    chosen = None
    if isinstance(want, str):
        chosen = next(
            (m for m in doc.get("machines", []) if m["name"].lower() == want.lower()),
            None,
        )
        if chosen is None:
            print(f"no machine named {want}", file=sys.stderr)
            return 2

    text = to_mermaid(doc, report, chosen) if "--mermaid" in flags else to_html(doc, report)

    dest = flags.get("--out")
    if isinstance(dest, str):
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {dest}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
