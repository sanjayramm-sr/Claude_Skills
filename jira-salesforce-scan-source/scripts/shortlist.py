#!/usr/bin/env python3
"""
Rank tickets and shortlist candidate Salesforce components for each.

This is retrieval, not judgment. It narrows thousands of components to a few
per ticket so their real source can be read and reasoned about. The scores
are a search relevance signal - they are NOT a verdict on whether the logic
already exists.

Usage:
    python shortlist.py <index.json> --tickets tickets.json [--out shortlist.json]
    python shortlist.py <index.json> --tickets tickets.json --candidates 8 --min-score 0.10

tickets.json: a list of objects, each with at least
    {"key": "CRM-418", "summary": "...", "description": "...",
     "priority": "High", "issue_type": "Bug"}
Optional per ticket: url, status, labels, components.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_PRIORITY_WEIGHTS = {"Critical": 5, "Highest": 5, "Major": 4, "High": 4,
                             "Medium": 3, "Minor": 2, "Low": 2, "Lowest": 1}
DEFAULT_TYPE_WEIGHTS = {"Bug": 3, "Story": 2, "Improvement": 2, "Task": 1,
                         "Sub-task": 1, "Epic": 1, "Spike": 1}

# Words that carry no signal about which component is relevant.
STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
    "was", "one", "our", "out", "has", "have", "this", "that", "with",
    "from", "they", "will", "would", "there", "their", "what", "when",
    "should", "need", "needs", "needed", "please", "also", "into", "only",
    "then", "than", "them", "these", "those", "some", "such", "being",
    "been", "were", "does", "done", "doing", "make", "made", "want",
    "wants", "able", "user", "users", "field", "fields", "record",
    "records", "salesforce", "ticket", "issue", "story", "bug", "task",
    "currently", "current", "instead", "however", "because", "which",
    "where", "while", "after", "before", "about", "could", "must",
    "update", "updated", "change", "changed", "add", "added", "new",
    "system", "systems", "process", "page", "value", "values", "data",
}


def tokenize(text):
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", (text or "").lower())
    out = set()
    for w in words:
        if w in STOPWORDS or len(w) < 3:
            continue
        out.add(w)
        # split snake_case / api names so Approval_Status__c matches "approval"
        for part in re.split(r"_+", w):
            if len(part) >= 3 and part not in STOPWORDS:
                out.add(part)
    return out


def score_component(ticket_tokens, comp_tokens, comp):
    if not ticket_tokens or not comp_tokens:
        return 0.0, []
    shared = ticket_tokens & comp_tokens
    if not shared:
        return 0.0, []

    # Overlap normalised by ticket length, so a long component can't win by bulk.
    base = len(shared) / len(ticket_tokens)

    # Rare-term bonus: a shared distinctive word matters more than a common one.
    rarity = sum(1 for t in shared if len(t) >= 7) * 0.02

    score = base + rarity

    # Test classes echo the language of what they test but implement nothing.
    if comp.get("is_test"):
        score *= 0.35
    # An inactive Flow is not live logic.
    if comp.get("active") is False:
        score *= 0.5

    return round(min(score, 1.0), 4), sorted(shared, key=len, reverse=True)[:12]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("index")
    ap.add_argument("--tickets", required=True)
    ap.add_argument("--weights",
                    help="Path to config.json (its 'ranking' section is used) "
                         "or a JSON file with priority_weights/type_weights directly. "
                         "Omit to use built-in defaults.")
    ap.add_argument("--out", default="shortlist.json")
    ap.add_argument("--candidates", type=int, default=6,
                    help="Max candidate components per ticket (default 6)")
    ap.add_argument("--min-score", type=float, default=0.08,
                    help="Drop candidates below this relevance (default 0.08)")
    args = ap.parse_args()

    index_data = json.loads(Path(args.index).read_text())
    components = index_data.get("components", index_data)
    tickets = json.loads(Path(args.tickets).read_text())
    if isinstance(tickets, dict):
        tickets = tickets.get("tickets", [])

    priority_weights, type_weights = dict(DEFAULT_PRIORITY_WEIGHTS), dict(DEFAULT_TYPE_WEIGHTS)
    if args.weights:
        raw = json.loads(Path(args.weights).read_text())
        ranking = raw.get("ranking", raw)
        priority_weights.update(ranking.get("priority_weights", {}))
        type_weights.update(ranking.get("type_weights", {}))

    if not components:
        print("WARNING: index is empty - every ticket will come back with no "
              "candidates. Check the metadata directory before reading "
              "anything into these results.", file=sys.stderr)

    # Pre-tokenize components once.
    comp_tokens = [(c, tokenize(c["searchable"] + " " + c["name"])) for c in components]

    results = []
    for t in tickets:
        pri = priority_weights.get(t.get("priority", "Medium"), 3)
        typ = type_weights.get(t.get("issue_type", "Task"), 1)
        rank_score = pri * 10 + typ

        ticket_tokens = tokenize(f"{t.get('summary','')} {t.get('description','')}")

        cands = []
        for comp, ctoks in comp_tokens:
            s, shared = score_component(ticket_tokens, ctoks, comp)
            if s >= args.min_score:
                cands.append({
                    "name": comp["name"],
                    "type": comp["type"],
                    "path": comp["path"],
                    "abs_path": comp["abs_path"],
                    "lines": comp.get("lines"),
                    "relevance": s,
                    "shared_terms": shared,
                    **({"is_test": True} if comp.get("is_test") else {}),
                    **({"flow_active": comp["active"]} if "active" in comp else {}),
                })
        cands.sort(key=lambda c: c["relevance"], reverse=True)

        results.append({
            **{k: t.get(k) for k in
               ("key", "url", "summary", "description", "priority",
                "issue_type", "status", "labels") if k in t},
            "rank_score": rank_score,
            "candidates": cands[: args.candidates],
            "total_above_threshold": len(cands),
        })

    results.sort(key=lambda r: r["rank_score"], reverse=True)

    Path(args.out).write_text(json.dumps({
        "ticket_count": len(results),
        "component_count": len(components),
        "tickets": results,
    }, indent=1))

    print(f"Shortlisted {len(results)} tickets against "
          f"{len(components)} components -> {args.out}", file=sys.stderr)
    print("\nRead the candidates' real source before judging. Relevance is a "
          "search score, not a verdict.\n", file=sys.stderr)
    for r in results:
        n = len(r["candidates"])
        top = f"{r['candidates'][0]['name']} ({r['candidates'][0]['relevance']})" if n else "-- none --"
        print(f"  {r.get('key','?'):12s} [{r.get('priority','?'):7s}"
              f" {r.get('issue_type','?'):11s}] {n} cands, top: {top}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
