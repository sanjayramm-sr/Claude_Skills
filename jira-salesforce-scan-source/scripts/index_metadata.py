#!/usr/bin/env python3
"""
Walk a Salesforce metadata tree and build a compact searchable index.

Why this exists: a real org has thousands of components. Reading them all
into context is impossible, so this extracts just enough per component
(type, name, path, identifiers, comments, labels) to shortlist candidates
cheaply. Full source is read later, only for the handful that matter.

Usage:
    python index_metadata.py <metadata_dir> [--out index.json]
    python index_metadata.py <metadata_dir> --types "Apex Class,Flow"

Accepts an SFDX project layout, a Metadata API retrieve, or an unzipped
export. Auto-detects the real root if handed a project or repo root.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# pattern -> component type. Globs are relative to the detected root.
COMPONENT_GLOBS = {
    "Apex Class": ["classes/*.cls", "**/classes/*.cls"],
    "Apex Trigger": ["triggers/*.trigger", "**/triggers/*.trigger"],
    "Flow": ["flows/*.flow-meta.xml", "flows/*.flow", "**/flows/*.flow*"],
    "Validation Rule": ["objects/**/validationRules/*.validationRule-meta.xml"],
    "Custom Field": ["objects/**/fields/*.field-meta.xml"],
    "Object": ["objects/**/*.object-meta.xml", "objects/*.object"],
    "Workflow": ["workflows/*.workflow-meta.xml", "workflows/*.workflow"],
    "Approval Process": ["approvalProcesses/*.approvalProcess-meta.xml"],
    "Visualforce Page": ["pages/*.page"],
    "LWC": ["lwc/**/*.js"],
    "Aura Component": ["aura/**/*.cmp"],
}

# Directories that indicate we've found the metadata root.
ROOT_MARKERS = {"classes", "triggers", "objects", "flows", "lwc", "aura", "pages"}

CODE_STOPWORDS = {
    "public", "private", "protected", "static", "void", "return", "class",
    "this", "true", "false", "null", "new", "for", "while", "final",
    "override", "global", "with", "sharing", "extends", "implements",
    "string", "integer", "boolean", "decimal", "double", "list", "set",
    "map", "object", "date", "datetime", "id", "type", "value", "values",
    "xml", "http", "www", "com", "urn", "salesforce", "soap", "sforce",
    "version", "encoding", "utf", "true", "apiversion", "status", "active",
}


def detect_root(start: Path) -> Path:
    """Find the directory that actually holds metadata folders."""
    if any((start / m).is_dir() for m in ROOT_MARKERS):
        return start
    # common nestings, cheapest first
    for candidate in [
        start / "force-app" / "main" / "default",
        start / "src",
        start / "unpackaged",
        start / "main" / "default",
    ]:
        if candidate.is_dir() and any((candidate / m).is_dir() for m in ROOT_MARKERS):
            return candidate
    # fall back to a bounded search
    for path in start.rglob("*"):
        if path.is_dir() and path.name in ROOT_MARKERS:
            return path.parent
    return start


def extract_searchable(text: str, comp_type: str) -> str:
    """
    Pull identifiers, comments and labels. Deliberately not the raw source:
    keeps the index small and the keyword matching meaningful.
    """
    parts = []

    # Apex/JS comments
    for m in re.finditer(r"//(.*)$", text, flags=re.M):
        parts.append(m.group(1))
    for m in re.finditer(r"/\*(.*?)\*/", text, flags=re.S):
        parts.append(m.group(1))

    # XML human-readable fields
    for tag in ("label", "description", "masterLabel", "fullName",
                "errorMessage", "name"):
        parts.extend(re.findall(rf"<{tag}>(.*?)</{tag}>", text, flags=re.S))

    # Identifiers, split on camelCase and underscores
    idents = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text)
    for ident in idents[:1200]:
        if ident.lower() in CODE_STOPWORDS:
            continue
        parts.append(ident)
        parts.extend(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", ident))

    blob = " ".join(parts).lower()
    blob = re.sub(r"[^a-z0-9_ ]+", " ", blob)
    blob = re.sub(r"\s+", " ", blob).strip()

    # cap per-component size so a huge class can't dominate the index
    return blob[:6000]


def clean_name(path: Path) -> str:
    name = path.name
    for suffix in (".cls", ".trigger", ".page", ".js", ".cmp",
                   ".flow-meta.xml", ".flow", ".object-meta.xml", ".object",
                   ".field-meta.xml", ".validationRule-meta.xml",
                   ".workflow-meta.xml", ".workflow",
                   ".approvalProcess-meta.xml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def build_index(root: Path, wanted_types=None):
    index = []
    seen = set()
    for comp_type, patterns in COMPONENT_GLOBS.items():
        if wanted_types and comp_type not in wanted_types:
            continue
        for pattern in patterns:
            for path in root.glob(pattern):
                if not path.is_file() or path in seen:
                    continue
                if "__tests__" in path.parts or "node_modules" in path.parts:
                    continue
                seen.add(path)
                try:
                    text = path.read_text(errors="ignore")
                except Exception as e:
                    print(f"  skip {path}: {e}", file=sys.stderr)
                    continue

                name = clean_name(path)
                entry = {
                    "name": name,
                    "type": comp_type,
                    "path": str(path.relative_to(root)),
                    "abs_path": str(path),
                    "lines": text.count("\n") + 1,
                    "searchable": extract_searchable(text, comp_type),
                }
                # flags worth knowing before trusting a match
                if comp_type == "Flow":
                    entry["active"] = "<status>Active</status>" in text
                if comp_type in ("Apex Class",) and re.search(
                    r"@isTest|testMethod", text
                ):
                    entry["is_test"] = True
                index.append(entry)
    return index


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("metadata_dir")
    ap.add_argument("--out", default="sf_index.json")
    ap.add_argument("--types", help="Comma-separated component types to include")
    args = ap.parse_args()

    start = Path(args.metadata_dir).expanduser().resolve()
    if not start.exists():
        print(f"ERROR: path does not exist: {start}", file=sys.stderr)
        return 2

    root = detect_root(start)
    if root != start:
        print(f"Detected metadata root: {root}", file=sys.stderr)

    wanted = {t.strip() for t in args.types.split(",")} if args.types else None
    index = build_index(root, wanted)

    Path(args.out).write_text(json.dumps(
        {"root": str(root), "components": index}, indent=1))

    if not index:
        print("WARNING: indexed 0 components. Wrong directory? Expected to "
              "find folders like classes/, triggers/, objects/, flows/ "
              "under the path given.", file=sys.stderr)
    else:
        by_type = {}
        for c in index:
            by_type[c["type"]] = by_type.get(c["type"], 0) + 1
        print(f"Indexed {len(index)} components -> {args.out}", file=sys.stderr)
        for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"  {n:5d}  {t}", file=sys.stderr)
        tests = sum(1 for c in index if c.get("is_test"))
        if tests:
            print(f"  ({tests} are test classes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
