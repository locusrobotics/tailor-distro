import argparse
import re

from typing import List, Optional
from pathlib import Path

from tailor_distro.blossom import Graph, GraphPackage


def show_changes(graph: Graph):
    for ros_distro, pkgs in graph.packages.items():
        for pkg in pkgs.values():
            if not pkg.apt_candidate_version:
                version = "None"
                sha = "None"
            else:
                # Parse the APT version <version>-<date>+git<sha>
                m = re.match(r"^(?P<version>.+)-(?P<date>\d{8}\.\d{6})\+git(?P<sha>[0-9a-f]+)$", pkg.apt_candidate_version)
                if m:
                    version, date, sha = m.group("version", "date", "sha")
                else:
                    raise Exception(f"Unexpected APT version format for {ros_distro} package {pkg.name}: {pkg.apt_candidate_version}")

            if pkg.version != version:
                print(f"{ros_distro} Package {pkg.name} version changed: {version} → {pkg.version}")
            if pkg.sha != sha:
                print(f"{ros_distro} Package {pkg.name} SHA changed: {sha} → {pkg.sha}")
            # The date will change for any graph generation, so we don't compare it


def _get_source_deps(pkg: GraphPackage, dep_type: Optional[str]) -> List[str]:
    if dep_type == "build":
        return pkg.build_depends(types=["source"])
    elif dep_type == "run":
        return pkg.run_depends(types=["source"])
    return pkg.get_source_depends()


def show_tree(graph: Graph, packages: List[str], dep_type: Optional[str] = None):
    if not packages:
        print("No packages specified. Use --packages to specify packages for the tree view.")
        return

    label = f" ({dep_type} only)" if dep_type else ""

    for ros_distro, pkgs in graph.packages.items():
        for pkg_name in packages:
            if pkg_name not in pkgs:
                continue

            print(f"[{ros_distro}] {pkg_name}{label}")
            _print_dep_tree(pkgs, pkg_name, dep_type, prefix="", visited=set())
            print()


def show_reverse_tree(graph: Graph, packages: List[str], dep_type: Optional[str] = None):
    if not packages:
        print("No packages specified. Use --packages to specify packages for the tree view.")
        return

    label = f" ({dep_type} only)" if dep_type else ""

    for ros_distro, pkgs in graph.packages.items():
        reverse_deps = _build_reverse_dep_map(pkgs, dep_type)
        for pkg_name in packages:
            if pkg_name not in pkgs:
                continue

            print(f"[{ros_distro}] {pkg_name} (reverse){label}")
            _print_reverse_dep_tree(reverse_deps, pkg_name, prefix="", visited=set())
            print()


def _print_dep_tree(pkgs, pkg_name: str, dep_type: Optional[str], prefix: str, visited: set):
    pkg = pkgs.get(pkg_name)
    if pkg is None:
        return

    deps = sorted(_get_source_deps(pkg, dep_type))
    for i, dep in enumerate(deps):
        is_last = (i == len(deps) - 1)
        connector = "└── " if is_last else "├── "

        if dep in visited:
            print(f"{prefix}{connector}{dep} (circular)")
            continue

        print(f"{prefix}{connector}{dep}")
        extension = "    " if is_last else "│   "
        visited.add(dep)
        _print_dep_tree(pkgs, dep, dep_type, prefix + extension, visited)


def _build_reverse_dep_map(pkgs, dep_type: Optional[str]):
    reverse_deps: dict[str, set[str]] = {pkg_name: set() for pkg_name in pkgs.keys()}
    for depender_name, depender_pkg in pkgs.items():
        for dep in _get_source_deps(depender_pkg, dep_type):
            if dep in reverse_deps:
                reverse_deps[dep].add(depender_name)
    return reverse_deps


def _print_reverse_dep_tree(reverse_deps, pkg_name: str, prefix: str, visited: set):
    dependents = sorted(reverse_deps.get(pkg_name, set()))
    for i, dep in enumerate(dependents):
        is_last = (i == len(dependents) - 1)
        connector = "└── " if is_last else "├── "

        if dep in visited:
            print(f"{prefix}{connector}{dep} (circular)")
            continue

        print(f"{prefix}{connector}{dep}")
        extension = "    " if is_last else "│   "
        visited.add(dep)
        _print_reverse_dep_tree(reverse_deps, dep, prefix + extension, visited)


def main():
    parser = argparse.ArgumentParser(description="CLI tools for tailor-distro")
    parser.add_argument("action", choices=["changes", "depends", "tree", "package"], help="Action to perform")
    parser.add_argument("graph", type=Path, help="Path to the graph YAML file")
    parser.add_argument("--packages", nargs="+", type=str, help="List of packages to show for depends/tree action")
    parser.add_argument("--dep-type", choices=["build", "run"], default=None,
                        help="Filter to only build or run dependencies (tree action)")
    parser.add_argument("--reverse", action="store_true",
                        help="Show reverse dependency tree (tree action)")

    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)

    if args.action == "changes":
        show_changes(graph)
    elif args.action == "tree":
        if args.reverse:
            show_reverse_tree(graph, args.packages or [], dep_type=args.dep_type)
        else:
            show_tree(graph, args.packages or [], dep_type=args.dep_type)
    elif args.action == "package":
        for package in graph.packages["ros1"].values():
            if package.was_downgraded():
                print(f"{package.name} was downgraded from {package.apt_candidate_version} to {package.version}")
                print(f"New version will be: {package.debian_version(graph.build_date)}")
    else:
        raise Exception(f"Unknown action: {args.action}")
