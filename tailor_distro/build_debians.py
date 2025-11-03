import argparse
import sys
import os
import subprocess
import shutil
import re

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from catkin_pkg.package import parse_package, InvalidPackage
from collections import defaultdict, deque

def find_packages(workspace_path):
    """Find all package.xml files in a workspace."""
    pkgs = {}
    for root, dirs, files in os.walk(workspace_path):
        if "CATKIN_IGNORE" in files or "COLCON_IGNORE" in files:
            continue

        if 'package.xml' in files:
            pkg_file = os.path.join(root, 'package.xml')
            try:
                pkg = parse_package(pkg_file)
                pkgs[pkg.name] = {
                    'name': pkg.name,
                    'path': root,
                    'build_depends': [d.name for d in pkg.build_depends],
                    'run_depends': [d.name for d in pkg.run_depends]
                }
                dirs[:] = []
            except InvalidPackage as e:
                print(f"Skipping invalid package.xml at {pkg_file}: {e}")
    return pkgs

def topo_sort_packages(pkgs):
    """Return a topologically sorted list of packages."""
    # Build graph: edges point pkg -> its dependencies
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    for pkg_name, pkg_data in pkgs.items():
        deps = pkg_data['build_depends'] + pkg_data['run_depends']
        for dep in deps:
            if dep in pkgs:  # only consider workspace packages
                graph[dep].append(pkg_name)
                in_degree[pkg_name] += 1

    # Kahn's algorithm
    queue = deque([name for name in pkgs if in_degree[name] == 0])
    sorted_list = []

    while queue:
        node = queue.popleft()
        sorted_list.append(pkgs[node])  # keep full dict
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_list) != len(pkgs):
        raise RuntimeError("Cycle detected or missing dependencies in workspace")

    return sorted_list

def remove_duplicates_in_changelog(package_path: Path) -> bool:
    """
    Remove duplicate version entries from a package's changelog.
    Supports any file named CHANGELOG.* (e.g., .rst, .md, .txt).
    Keeps the first occurrence of each version.
    Returns True if any duplicates were removed.
    """
    changelog_files = list(package_path.glob("CHANGELOG.*"))
    if not changelog_files:
        return False

    # We'll just use the first changelog file we find
    changelog_file = changelog_files[0]
    lines = changelog_file.read_text(encoding="utf-8").splitlines()

    # Match versions at the start of the line: e.g., "1.16.0"
    version_pattern = re.compile(r"^(\d+\.\d+\.\d+)\b")
    seen_versions = set()
    cleaned_lines = []

    for line in lines:
        match = version_pattern.match(line)
        if match:
            version = match.group(1)
            if version in seen_versions:
                continue  # skip duplicates
            seen_versions.add(version)
        cleaned_lines.append(line)

    # Only write back if something changed
    if cleaned_lines != lines:
        changelog_file.write_text("\n".join(cleaned_lines), encoding="utf-8")
        return True

    return False


def build_debian(pkg):
    """Run bloom for a single package."""
    print(f"Building package: {pkg['name']} at {pkg['path']}")
    subprocess.run(
        ['bloom-generate', 'rosdebian', '--os-name', 'ubuntu', '--os-version', 'jammy', '--ros-distro', 'locusrobotics-hotdog-origin1'],
        cwd=pkg['path'],
        check=True
    )

    subprocess.run(['fakeroot', 'debian/rules', 'binary'], cwd=pkg['path'], check=True)

def parallel_build(packages, max_workers=8):
    # Build helper mappings
    name_to_pkg = {pkg['name']: pkg for pkg in packages}
    dep_count = {pkg['name']: len(pkg.get('build_depends', [])) for pkg in packages}
    dependents = defaultdict(list)

    for pkg in packages:
        for dep in pkg.get('build_depends', []):
            dependents[dep].append(pkg['name'])

    # Start with packages that have no dependencies
    ready = deque([pkg_name for pkg_name, count in dep_count.items() if count == 0])
    futures = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while ready or futures:
            # Submit ready packages
            while ready:
                pkg_name = ready.popleft()
                pkg = name_to_pkg[pkg_name]
                futures[executor.submit(build_debian, pkg)] = pkg_name

            # Wait for any package to finish
            for future in as_completed(futures):
                finished_pkg_name = futures.pop(future)
                # Update dependents
                for dependent in dependents[finished_pkg_name]:
                    dep_count[dependent] -= 1
                    if dep_count[dependent] == 0:
                        ready.append(dependent)
                break  # re-evaluate ready queue

def build_debians(workspace: Path):
    print(f"building debians for packages under: {workspace}")

    print("Collected packages to build")
    pkgs = find_packages(workspace)

    sorted_pkgs = topo_sort_packages(pkgs)

    # Remove all debian folders
    for debian_dir in workspace.rglob("debian"):
        shutil.rmtree(debian_dir)

    # Remove previously built .deb files

    # Optional: remove build/devel/install
    for folder in ["build", "devel", "install"]:
        path = Path(workspace.parent) / folder
        if path.exists():
            shutil.rmtree(path)

    for pkg in sorted_pkgs:
        if remove_duplicates_in_changelog(Path(pkg["path"])):
            print(f"Removed duplicates in {pkg['path']}")

    # Find already build debians
    #built_debs = []
    #for deb_file in workspace.rglob("*.deb"):
    #    built_debs.append(os.path.basename(deb_file))

    print("Building packages in order:")
    #parallel_build(sorted_pkgs)
    for pkg in sorted_pkgs:
        #skip = False

        #for deb in built_debs:
        #    if pkg["name"] in deb:
        #        print(f"Skipping {pkg['name']}, debian {deb} is already built")
        #        skip = True
        #        break

        #if skip:
        #    continue

        build_debian(pkg)

def main():
    parser = argparse.ArgumentParser(description="Build per package debians")
    #parser.add_argument('--release-track', type=str, required=True)
    #parser.add_argument('--release-label', type=str, required=True)
    #parser.add_argument('--debian-version', type=str, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()

    sys.exit(build_debians(**vars(args)))


if __name__ == '__main__':
    main()
