"""CLI tool: print a dependency-trigger tree from a build report YAML."""
import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import yaml


def load_report(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_trigger_tree(rebuilt: List[dict]) -> tuple[Dict[str, List[str]], List[str]]:
    """Return (parent->children map, root package names)."""
    children: Dict[str, List[str]] = defaultdict(list)
    parent_of: Dict[str, Optional[str]] = {}

    for pkg in rebuilt:
        name = pkg["name"]
        trigger = pkg.get("trigger", "unknown")
        if trigger.startswith("rdep:"):
            parent = trigger[len("rdep:"):]
            parent_of[name] = parent
            children[parent].append(name)
        elif trigger.startswith("ros1_dep:"):
            parent = trigger[len("ros1_dep:"):]
            parent_of[name] = parent
            children[parent].append(name)
        else:
            parent_of[name] = None

    roots = [pkg["name"] for pkg in rebuilt if parent_of.get(pkg["name"]) is None]
    return children, roots


def count_descendants(name: str, children: Dict[str, List[str]], memo: Dict[str, int] = {}) -> int:
    if name in memo:
        return memo[name]
    total = sum(1 + count_descendants(c, children, memo) for c in children.get(name, []))
    memo[name] = total
    return total


def print_tree(
    name: str,
    children: Dict[str, List[str]],
    pkg_info: Dict[str, dict],
    prefix: str = "",
    last: bool = True,
):
    connector = "└── " if last else "├── "
    pkg = pkg_info.get(name, {})
    trigger = pkg.get("trigger", "")
    sha_note = ""
    if trigger == "sha_change":
        old = pkg.get("previous_sha", "?")
        new = pkg.get("sha", "?")
        sha_note = f"  [{old} → {new}]"
    elif trigger == "new_package":
        sha_note = "  [new]"
    elif trigger == "rebuild_all":
        sha_note = "  [rebuild_all]"

    n = count_descendants(name, children, {})
    cascade_note = f"  (+{n})" if n else ""

    print(f"{prefix}{connector}{name}{sha_note}{cascade_note}")

    child_prefix = prefix + ("    " if last else "│   ")
    kids = sorted(children.get(name, []))
    for i, child in enumerate(kids):
        print_tree(child, children, pkg_info, child_prefix, last=(i == len(kids) - 1))


def main():
    parser = argparse.ArgumentParser(
        description="Show a tree of which packages triggered others to rebuild."
    )
    parser.add_argument("report", type=Path, help="Path to build report YAML")
    parser.add_argument(
        "--roots-only", action="store_true",
        help="Print only the root trigger packages, not their cascades",
    )
    args = parser.parse_args()

    if not args.report.exists():
        print(f"error: {args.report} not found", file=sys.stderr)
        sys.exit(1)

    report = load_report(args.report)
    rebuilt = report.get("rebuilt", [])

    if not rebuilt:
        print("No packages were rebuilt.")
        return

    pkg_info = {p["name"]: p for p in rebuilt}
    children, roots = build_trigger_tree(rebuilt)

    print(
        f"Build: {report.get('build_date', '?')}  "
        f"distro: {report.get('ros_distro', '?')}  "
        f"rebuilt: {report.get('rebuilt_count', len(rebuilt))}  "
        f"reused: {report.get('reused_count', '?')}"
    )
    print()

    if args.roots_only:
        for root in sorted(roots):
            pkg = pkg_info.get(root, {})
            trigger = pkg.get("trigger", "?")
            old = pkg.get("previous_sha", "?")
            new = pkg.get("sha", "?")
            cascade = count_descendants(root, children, {})
            sha_note = f"[{old} → {new}]" if trigger == "sha_change" else f"[{trigger}]"
            cascade_note = f"  (+{cascade} downstream)" if cascade else ""
            print(f"  {root}  {sha_note}{cascade_note}")
        return

    for i, root in enumerate(sorted(roots)):
        print_tree(root, children, pkg_info, prefix="", last=(i == len(roots) - 1))


if __name__ == "__main__":
    main()
