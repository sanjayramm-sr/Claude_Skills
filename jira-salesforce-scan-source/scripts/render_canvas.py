#!/usr/bin/env python3
"""
Generates the Slack deliverables from the same tickets JSON the dashboard
uses: the full canvas (a table per board) and the short chat summary that
links to it.

This exists for the same reason render_dashboard.py does. Describing the
table in prose meant every run reinvented it and quietly produced something
thinner — missing the Suggested changes column, or collapsing to a counts-only
summary. Generating it from data makes the output identical every time.

Usage:
    python render_canvas.py --tickets tickets.json --boards boards.json \\
        --jira-site "https://yourco.atlassian.net" \\
        --source-note "Live org scan" \\
        --out-canvas canvas.md --out-message message.txt

Then pass the canvas file's contents to slack_create_canvas (first run) or
slack_update_canvas (every run after — reuse the canvas_id in config.json),
and the message file's contents to slack_send_message.

tickets.json uses the same schema as render_dashboard.py:
    key, project, priority, issuetype, status, summary,
    kind ("cfg"|"exist"|"new"|"epic"|null),
    read, touches, suggest, blockers
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_PRI_W = {"Critical": 5, "Highest": 5, "Major": 4, "High": 4,
                  "Medium": 3, "Minor": 2, "Low": 2, "Lowest": 1}
DEFAULT_TYPE_W = {"Bug": 3, "Story": 2, "Improvement": 2, "Task": 1,
                   "Sub-task": 1, "Epic": 1, "Spike": 1}

KIND_LABEL = {
    "cfg": "Config / admin",
    "exist": "Touches existing",
    "new": "New logic",
    "epic": "Epic — needs breakdown",
}

# The five columns are fixed. Do not reorder or drop any of them.
# Board is deliberately NOT a column — each table already sits under its
# own board heading, so repeating it in every row is pure noise.
HEADER = ("|Ticket|Requirement|Components to touch|"
          "Suggested changes|Open/Watch out|")
DIVIDER = "|---|---|---|---|---|"


def cell(s):
    """Make arbitrary text safe inside a Markdown table cell."""
    if not s:
        return "—"
    s = str(s).replace("\n", " ").strip()
    # structural pipes would split the cell
    s = s.replace("|", "\\|")
    # a lone * (e.g. in a glob like classes/*.cls) starts emphasis parsing
    # and silently eats the rest of the cell — this bit us for real once
    s = s.replace("*", "\\*")
    # <Foo> reads as an HTML tag and gets swallowed by the renderer
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    # restore the one tag we do want
    s = s.replace("&lt;br&gt;", "<br>")
    return s


def sort_key(t, boards, pri_w, type_w):
    cfg = boards.get(t["project"], {})
    rank = cfg.get("rank", 99)
    bug_first = 0 if t.get("issuetype") == "Bug" else 1
    score = -(pri_w.get(t.get("priority"), 3) * 10
              + type_w.get(t.get("issuetype"), 1))
    return (rank, bug_first, score)


def build_canvas(tickets, boards, jira_site, source_note, pri_w, type_w):
    lines = []
    lines.append(source_note)
    lines.append("")

    counts = {}
    for t in tickets:
        k = t.get("kind") or "unassessed"
        counts[k] = counts.get(k, 0) + 1
    summary_bits = [f"{n} {KIND_LABEL.get(k, k)}" for k, n in sorted(counts.items())]
    lines.append(f"**{len(tickets)} open tickets** — " + " · ".join(summary_bits))
    lines.append("")

    ordered_boards = sorted(
        {t["project"] for t in tickets},
        key=lambda b: boards.get(b, {}).get("rank", 99),
    )

    for board in ordered_boards:
        bcfg = boards.get(board, {})
        rows = sorted([t for t in tickets if t["project"] == board],
                      key=lambda t: sort_key(t, boards, pri_w, type_w))
        note = ""
        if bcfg.get("usesSprints") is False:
            note = " — no active sprint, showing all open tickets"
        lines.append(f"## {board} — {bcfg.get('name', board)}{note}")
        lines.append("")
        lines.append(HEADER)
        lines.append(DIVIDER)
        for t in rows:
            link = f"[{t['key']}]({jira_site.rstrip('/')}/browse/{t['key']})"
            meta = f"*{cell(t.get('priority'))} · {cell(t.get('issuetype'))} · {cell(t.get('status'))}*"
            ticket_cell = f"{link} — {cell(t.get('summary'))} <br>{meta}"
            if not t.get("read") and not t.get("suggest"):
                req = "_Not yet analysed against Salesforce._"
                touches = suggest = "—"
            else:
                req = cell(t.get("read"))
                touches = cell(t.get("touches"))
                suggest = cell(t.get("suggest"))
            lines.append(
                f"|{ticket_cell}|{req}|{touches}|{suggest}|{cell(t.get('blockers'))}|"
            )
        lines.append("")

    return "\n".join(lines)


def build_message(tickets, boards, jira_site, canvas_url, source_note, pri_w, type_w):
    """Short chat summary. Must carry real suggestions, not just counts."""
    ordered = sorted(tickets, key=lambda t: sort_key(t, boards, pri_w, type_w))
    counts = {}
    for t in tickets:
        k = t.get("kind") or "unassessed"
        counts[k] = counts.get(k, 0) + 1

    out = []
    out.append("*Sprint brief ready*")
    out.append("")
    board_order = " → ".join(sorted(
        {t["project"] for t in tickets},
        key=lambda b: boards.get(b, {}).get("rank", 99)))
    out.append(f"Boards: {board_order} · *{len(tickets)} open tickets* — "
               + " · ".join(f"{n} {KIND_LABEL.get(k, k)}" for k, n in sorted(counts.items())))
    out.append(f"_{source_note}_")
    out.append("")
    out.append("*Top items and what to actually do:*")

    shown = 0
    for t in ordered:
        if shown >= 5:
            break
        suggest = (t.get("suggest") or "").strip()
        if not suggest:
            continue
        # keep each to one scannable line
        short = suggest if len(suggest) <= 200 else suggest[:197].rsplit(" ", 1)[0] + "…"
        out.append(f"• *<{jira_site.rstrip('/')}/browse/{t['key']}|{t['key']}>* "
                   f"[{t.get('priority')}] {t.get('summary')}")
        out.append(f"    → {short}")
        shown += 1

    if shown == 0:
        out.append("_No suggestions generated — no Salesforce source was available "
                   "to analyse against. See the canvas for the ranked ticket list._")

    if canvas_url:
        out.append("")
        out.append(f"Full detail (all {len(tickets)} tickets, every column): <{canvas_url}|open the canvas>")
    return "\n".join(out)


def validate_table(canvas_md):
    """
    Every row in a table block must have the same number of unescaped pipes.
    A mismatch renders as a phantom empty column or a swallowed cell — we
    shipped that bug once; catch it here instead of in Slack.
    Returns a list of problem descriptions (empty means clean).
    """
    problems = []
    block = []
    for line in canvas_md.splitlines():
        if line.startswith("|"):
            block.append(line)
            continue
        if block:
            problems += _check_block(block)
            block = []
    if block:
        problems += _check_block(block)
    return problems


def _check_block(block):
    counts = {}
    for line in block:
        # count structural pipes only, ignoring \| escapes
        n = line.replace("\\|", "").count("|")
        counts.setdefault(n, []).append(line[:70])
    if len(counts) > 1:
        out = ["Table has rows with mismatched column counts:"]
        for n, samples in sorted(counts.items()):
            out.append(f"    {n} pipes ({len(samples)} row(s)) e.g. {samples[0]}…")
        return out
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickets", required=True)
    ap.add_argument("--boards")
    ap.add_argument("--weights",
                    help="Path to config.json (its 'ranking' section is used) "
                         "or a JSON file with priority_weights/type_weights directly. "
                         "Omit to use built-in defaults.")
    ap.add_argument("--jira-site", required=True)
    ap.add_argument("--source-note", default="Salesforce source not recorded.",
                    help="One line stating what was scanned and how fresh it is")
    ap.add_argument("--canvas-url", default="", help="Existing canvas URL, for the message link")
    ap.add_argument("--out-canvas", default="canvas.md")
    ap.add_argument("--out-message", default="message.txt")
    args = ap.parse_args()

    tickets = json.loads(Path(args.tickets).read_text())
    if isinstance(tickets, dict):
        tickets = tickets.get("tickets", [])
    boards = json.loads(Path(args.boards).read_text()) if args.boards else {}

    pri_w, type_w = dict(DEFAULT_PRI_W), dict(DEFAULT_TYPE_W)
    if args.weights:
        raw = json.loads(Path(args.weights).read_text())
        ranking = raw.get("ranking", raw)  # accept full config.json or just its ranking block
        pri_w.update(ranking.get("priority_weights", {}))
        type_w.update(ranking.get("type_weights", {}))

    if not tickets:
        print("ERROR: no tickets to render.", file=sys.stderr)
        return 2

    canvas = build_canvas(tickets, boards, args.jira_site, args.source_note, pri_w, type_w)
    message = build_message(tickets, boards, args.jira_site,
                            args.canvas_url, args.source_note, pri_w, type_w)

    Path(args.out_canvas).write_text(canvas)
    Path(args.out_message).write_text(message)

    problems = validate_table(canvas)
    n_sugg = sum(1 for t in tickets if (t.get("suggest") or "").strip())
    print(f"Canvas  -> {args.out_canvas} ({len(canvas)} chars)", file=sys.stderr)
    print(f"Message -> {args.out_message} ({len(message)} chars)", file=sys.stderr)
    print(f"{n_sugg}/{len(tickets)} tickets carry a suggestion.", file=sys.stderr)

    if problems:
        print("\nTABLE VALIDATION FAILED — do not post this:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("Table validation: OK (uniform column counts).", file=sys.stderr)

    if len(message) > 3900:
        print("WARNING: message is close to Slack's 5,000-char cap.", file=sys.stderr)
    if n_sugg == 0:
        print("WARNING: no suggestions present — was a Salesforce source actually "
              "scanned? Check Step 3 before delivering.", file=sys.stderr)

    print("\nNOT DONE YET: the canvas has been generated, not posted. "
          "Push it with slack_update_canvas (or slack_create_canvas on first "
          "run), send the message, then read both back to confirm.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
