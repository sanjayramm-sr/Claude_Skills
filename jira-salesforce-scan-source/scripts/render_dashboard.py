#!/usr/bin/env python3
"""
Fills the dashboard HTML template with real ticket data.

This exists so the dashboard looks and behaves identically every time it's
produced — Claude fills in JSON, not hand-authored HTML/JS, which is what
makes "every time I invoke this" actually mean the same output shape.

Usage:
    python render_dashboard.py --tickets tickets.json --boards boards.json \
        --sf-date "Sep 17, 2026" --jira-site "https://yourcompany.atlassian.net" \
        --out dashboard.html

tickets.json: a list of objects, each:
    {"key": "LTOR-1188", "project": "LTOR", "priority": "Critical",
     "issuetype": "Story", "status": "In Progress", "summary": "...",
     "kind": "cfg" | "exist" | "new" | "epic",
     "read": "...", "touches": "...", "suggest": "...", "blockers": "..." | null}
kind, read, touches, suggest may be null for a ticket not yet analyzed
(the template shows a "not yet analyzed" placeholder for those).

boards.json: the user's board config, in their stated priority order:
    {"LTOR": {"name": "Lead-to-Opportunity Requests", "rank": 0, "usesSprints": true},
     "QTC":  {"name": "Quote-to-Cash (Capabilities)",  "rank": 1, "usesSprints": false}}
If boards.json is omitted, every ticket's project is treated as its own
unranked board (rank 0, usesSprints true) — the dashboard still works, it
just won't group or order by board preference.
"""
import argparse
import json
import sys
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "dashboard_template.html"


DEFAULT_PRI_W = {"Critical": 5, "Highest": 5, "Major": 4, "High": 4,
                  "Medium": 3, "Minor": 2, "Low": 2, "Lowest": 1}
DEFAULT_TYPE_W = {"Bug": 3, "Story": 2, "Improvement": 2, "Task": 1,
                   "Sub-task": 1, "Epic": 1, "Spike": 1}


def infer_boards(tickets):
    boards = {}
    for i, proj in enumerate(sorted({t["project"] for t in tickets})):
        boards[proj] = {"name": proj, "rank": i, "usesSprints": True}
    return boards


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickets", required=True, help="Path to tickets JSON")
    ap.add_argument("--boards", help="Path to board config JSON (optional)")
    ap.add_argument("--weights",
                    help="Path to config.json (its 'ranking' section is used) "
                         "or a JSON file with priority_weights/type_weights directly. "
                         "Omit to use built-in defaults.")
    ap.add_argument("--sf-date", required=True, help='e.g. "Sep 17, 2026"')
    ap.add_argument("--jira-site", required=True, help="e.g. https://yourco.atlassian.net")
    ap.add_argument("--out", default="dashboard.html")
    args = ap.parse_args()

    if not TEMPLATE_PATH.exists():
        print(f"ERROR: template not found at {TEMPLATE_PATH}", file=sys.stderr)
        return 2

    tickets = json.loads(Path(args.tickets).read_text())
    if isinstance(tickets, dict):
        tickets = tickets.get("tickets", [])

    if args.boards:
        boards = json.loads(Path(args.boards).read_text())
    else:
        boards = infer_boards(tickets)
        print("No --boards given; inferred one unranked board per project. "
              "Pass --boards for real board grouping/priority order.", file=sys.stderr)

    # required fields per ticket; fill sensible blanks for an unanalyzed ticket
    required = ("key", "project", "priority", "issuetype", "status", "summary")
    clean = []
    for t in tickets:
        missing = [f for f in required if not t.get(f)]
        if missing:
            print(f"WARNING: {t.get('key','?')} missing {missing} — skipping", file=sys.stderr)
            continue
        clean.append({
            "key": t["key"], "project": t["project"], "priority": t["priority"],
            "issuetype": t["issuetype"], "status": t["status"], "summary": t["summary"],
            "kind": t.get("kind"), "read": t.get("read"), "touches": t.get("touches"),
            "suggest": t.get("suggest"), "blockers": t.get("blockers"),
        })

    if not clean:
        print("WARNING: 0 valid tickets after cleaning — dashboard will render empty.",
              file=sys.stderr)

    pri_w, type_w = dict(DEFAULT_PRI_W), dict(DEFAULT_TYPE_W)
    if args.weights:
        raw = json.loads(Path(args.weights).read_text())
        ranking = raw.get("ranking", raw)
        pri_w.update(ranking.get("priority_weights", {}))
        type_w.update(ranking.get("type_weights", {}))

    html = TEMPLATE_PATH.read_text()
    html = html.replace("__BOARD_CONFIG_JSON__", json.dumps(boards))
    html = html.replace("__SF_READ_DATE__", args.sf_date.replace('"', '\\"'))
    html = html.replace("__JIRA_SITE__", args.jira_site.rstrip("/"))
    html = html.replace("__PRIORITY_WEIGHTS_JSON__", json.dumps(pri_w))
    html = html.replace("__TYPE_WEIGHTS_JSON__", json.dumps(type_w))
    html = html.replace("__TICKETS_JSON__", json.dumps(clean))

    Path(args.out).write_text(html)
    kinds = {}
    for t in clean:
        kinds[t["kind"] or "unanalyzed"] = kinds.get(t["kind"] or "unanalyzed", 0) + 1
    print(f"Wrote {args.out} — {len(clean)} tickets across {len(boards)} boards", file=sys.stderr)
    for k, n in sorted(kinds.items()):
        print(f"  {n:3d}  {k}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
