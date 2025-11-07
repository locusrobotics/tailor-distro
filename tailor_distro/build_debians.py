import argparse
import sys
import os
import subprocess
import shutil
import re
import yaml

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from catkin_pkg.package import parse_package, InvalidPackage
from collections import defaultdict, deque


import os
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from catkin_pkg.topological_order import topological_order

from .generate_bundle_templates import get_packages_in_workspace

from bloom.generators.rosdebian import RosDebianGenerator


ROS_ENV_VARS = [
    "ROS_ROOT",
    "ROS_PACKAGE_PATH",
    "ROS_MASTER_URI",
    "ROS_VERSION",
    "ROS_PYTHON_VERSION",
    "CMAKE_PREFIX_PATH",
    "ROS_ETC_DIR"
]


def find_packages(workspace_path):
    """Find all package.xml files in a workspace."""

    result = subprocess.run(["colcon", "list", "--base-paths", workspace_path, "-t"], stdout=subprocess.PIPE)

    lines = result.stdout.decode().strip().split("\n")

    pkgs = []

    for line in lines:
        print(line)
        pkg, path, _ = line.split()

        pkgs.append({
            "name": pkg,
            "path": os.path.abspath(path)
        })

    return pkgs


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
                    'buildtool_depends': [d.name for d in pkg.buildtool_depends],
                    'run_depends': [d.name for d in pkg.run_depends],
                    'exec_depends': [d.name for d in pkg.exec_depends],
                }
                dirs[:] = []
            except InvalidPackage as e:
                print(f"Skipping invalid package.xml at {pkg_file}: {e}")
    return pkgs



def compute_build_order(all_packages, target_packages):
    from collections import defaultdict, deque

    reachable = set()
    stack = list(target_packages)

    while stack:
        pkg = stack.pop()
        if pkg in all_packages and pkg not in reachable:
            reachable.add(pkg)
            info = all_packages[pkg]
            deps = (info.get('build_depends', []) +
                    info.get('buildtool_depends', []) +
                    info.get('run_depends', []) +
                    info.get('exec_depends', []))  # Include exec_depends
            for dep in deps:
                if dep in all_packages:
                    stack.append(dep)

    deps = defaultdict(set)
    rev_deps = defaultdict(set)
    for pkg in reachable:
        info = all_packages[pkg]
        pkg_deps = set(info.get('build_depends', []) +
                       info.get('buildtool_depends', []) +
                       info.get('run_depends', []) +
                       info.get('exec_depends', []))  # Include exec_depends
        pkg_deps &= reachable
        deps[pkg] = pkg_deps
        for d in pkg_deps:
            rev_deps[d].add(pkg)

    indegree = {pkg: len(deps[pkg]) for pkg in reachable}
    ready = deque(sorted([pkg for pkg in reachable if indegree[pkg] == 0]))
    build_order_names = []

    while ready:
        pkg = ready.popleft()
        build_order_names.append(pkg)
        for dependent in sorted(rev_deps[pkg]):  # Sort for deterministic order
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready = deque(sorted(ready))  # Re-sort after adding

    if len(build_order_names) != len(reachable):
        missing = reachable - set(build_order_names)
        raise RuntimeError(f"Circular dependency detected: {missing}")

    build_order_dicts = [all_packages[pkg] for pkg in build_order_names]

    return build_order_dicts




def topological_sort_catkin_package_map(package_map, root_names=None):
    """
    Perform a topological sort on a dict of catkin_pkg Package objects using all dependency types.

    Args:
        package_map (dict): Mapping of package name -> catkin_pkg.package.Package
        root_names (list): Optional list of root package names to start from

    Returns:
        List[Package]: Sorted list of Package objects
    """
    # Step 1: Determine reachable packages
    if root_names is None:
        reachable = set(package_map.keys())
    else:
        reachable = set()
        stack = list(root_names)
        while stack:
            name = stack.pop()
            if name in package_map and name not in reachable:
                reachable.add(name)
                pkg = package_map[name]
                deps = (
                    [d.name for d in pkg.build_depends] +
                    [d.name for d in pkg.buildtool_depends] +
                    [d.name for d in pkg.run_depends] +
                    [d.name for d in pkg.exec_depends] +
                    [d.name for d in pkg.test_depends]
                )
                for dep in deps:
                    if dep in package_map:
                        stack.append(dep)

    # Step 2: Build dependency graph
    deps = defaultdict(set)
    rev_deps = defaultdict(set)
    for name in reachable:
        pkg = package_map[name]
        pkg_deps = set(
            d.name for d in (
                pkg.build_depends +
                pkg.buildtool_depends +
                pkg.run_depends +
                pkg.exec_depends +
                pkg.test_depends
            )
            if d.name in reachable
        )
        deps[name] = pkg_deps
        for dep in pkg_deps:
            rev_deps[dep].add(name)

    # Step 3: Kahn's algorithm
    indegree = {name: len(deps[name]) for name in reachable}
    ready = deque(sorted([name for name in reachable if indegree[name] == 0]))
    sorted_names = []

    while ready:
        name = ready.popleft()
        sorted_names.append(name)
        for dependent in sorted(rev_deps[name]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready = deque(sorted(ready))  # Keep deterministic order

    if len(sorted_names) != len(reachable):
        missing = reachable - set(sorted_names)
        raise RuntimeError(f"Circular dependency detected: {missing}")

    return [package_map[name] for name in sorted_names]



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



def get_package_env(path):
    # Run a shell that sources the setup script and prints the environment
    command = f"bash -c 'source {path} && env'"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    env = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        env[key] = value
    return env


def generate_shlibs_local(pkg_path: Path, staging_prefix: Path) -> Path:
    shlibs_local_path = pkg_path / "shlibs.local"

    # Find only dirs with shared libraries
    lib_dirs = {p.parent for p in staging_prefix.rglob("*.so*") if p.is_file()}

    with shlibs_local_path.open("w") as f:
        for lib_file in staging_prefix.rglob("*.so*"):
            if not lib_file.is_file():
                continue
            try:
                result = subprocess.run(
                    ["readelf", "-d", str(lib_file)],
                    capture_output=True,
                    text=True,
                    check=True
                )
                soname = None
                for line in result.stdout.splitlines():
                    if "SONAME" in line:
                        soname = line.split("Library:")[-1].strip()
                        break

                if soname:
                    parts = soname.split(".")
                    version = parts[-2] if len(parts) > 1 else "0"
                    pkg_name = f"local-{parts[0]}"
                    f.write(f"{soname} {version} {pkg_name} (>= {version})\n")
            except subprocess.CalledProcessError:
                print(f"Warning: could not read SONAME for {lib_file}")

    print(f"Generated shlibs.local at {shlibs_local_path}")
    return shlibs_local_path, lib_dirs

def build_debian(pkg, env, debug: bool = False, staging_prefix="/home/jprestwood/build-per-package/install", no_check: bool = False) -> dict:

    pkg_path = Path(pkg["path"]).resolve()
    staging_prefix = Path(staging_prefix).resolve()
    staging_prefix.mkdir(parents=True, exist_ok=True)

    # Step 1: Generate Debian packaging with bloom
    if debug:
        print(f"[INFO] Generating Debian packaging for {pkg_path.name}...")
    subprocess.run(
        [
            'bloom-generate',
            'rosdebian',
            '--os-name', 'ubuntu',
            '--os-version', 'jammy',
            '--ros-distro', 'ros1',
            '-d'
        ],
        cwd=pkg_path,
        check=True
    )

    # Step 2: Build the .deb using fakeroot with the passed-in env
    if env is None:
        env = {}


    build_env = env.copy()
    cmake_prefix = f"{staging_prefix}:{build_env.get('CMAKE_PREFIX_PATH', '')}"
    staging_prefix = staging_prefix / "opt/ros/ros1"
    build_env["CMAKE_PREFIX_PATH"] = staging_prefix

    shlibs_local, lib_dirs = generate_shlibs_local(Path(pkg["path"]), staging_prefix)

    dpkg_shlibdeps_args = f"--local-shlibs={shlibs_local} "
    for lib_dir in lib_dirs:
        dpkg_shlibdeps_args += f"-l{lib_dir} "

    build_env["DPKG_SHLIBDEPS_ARGS"] = dpkg_shlibdeps_args


    print(build_env["DPKG_SHLIBDEPS_ARGS"])

    print(build_env["PATH"])

    #return

    if pkg["name"] == "ros_environment":
        print("Unsetting ROS_DISTRO")
        ros_distro = build_env["ROS_DISTRO"]
        del build_env["ROS_DISTRO"]

    if debug:
        print(f"[INFO] Building .deb for {pkg_path.name} with CMAKE_PREFIX_PATH={cmake_prefix}...")
    subprocess.run(
        ["fakeroot", "debian/rules", "binary"],
        cwd=pkg_path,
        check=True,
        env=build_env
    )

    if pkg["name"] == "ros_environment":

        build_env["ROS_DISTRO"] = ros_distro

    # Step 3: Find the generated .deb
    deb_files = list(pkg_path.parent.glob(f"*.deb"))
    if not deb_files:
        raise RuntimeError(f"[ERROR] No .deb files found for {pkg_path.name}")
    deb_file_path = str(deb_files[0].resolve())

    # Step 4: Install the .deb to the staging prefix
    if debug:
        print(f"[INFO] Installing {pkg_path.name} to staging prefix {staging_prefix}...")

    for deb in deb_files:
        subprocess.run(
            ["dpkg", "-i", deb.resolve()],
            check=True
        )

    # Step 5: Update the env dictionary for future builds
    new_env = build_env.copy()
    new_env["CMAKE_PREFIX_PATH"] = f"{staging_prefix}:{new_env.get('CMAKE_PREFIX_PATH', '')}"
    #new_env["LD_LIBRARY_PATH"] = (
    #    f"{staging_prefix}/opt/ros/ros1/lib/x86_64-linux-gnu:{staging_prefix}/opt/ros/ros1/lib:"
    #    f"{new_env.get('LD_LIBRARY_PATH', '')}"
    #)

    if debug:
        print(f"[INFO] Updated environment for future builds: CMAKE_PREFIX_PATH={new_env['CMAKE_PREFIX_PATH']}")
        print(f"[INFO] Built .deb: {deb_file_path}")

    return new_env
"""
    print(f"Building: {pkg['name']}...", end='')

    stdout = subprocess.PIPE if not debug else None
    stderr = subprocess.STDOUT if not debug else None

    for key, val in env.items():
        print(f"{key}={val}")

    if pkg["name"] == "ros_environment":
        ros_distro = env["ROS_DISTRO"]
        del env["ROS_DISTRO"]

    try:
        bloom_env = env.copy()

        subprocess.run(
            [
                'bloom-generate',
                'rosdebian',
                '--os-name', 'ubuntu',
                '--os-version', 'jammy',
                '--ros-distro', 'ros1',
                '-d'
            ],
            cwd=pkg['path'],
            check=True,
            stdout=stdout,
            stderr=stderr,
            env=bloom_env,
        )
    except subprocess.CalledProcessError as e:
        print()
        print(f"failed to run bloom-generate on {pkg['name']}")
        if not debug:
            print(e.stdout.decode())
        raise

    try:
        subprocess.run(
            ['fakeroot', 'debian/rules', 'binary'],
            cwd=pkg['path'],
            check=True,
            stdout=stdout,
            stderr=stderr,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        print()
        print(f"failed to build {pkg['name']}")
        if not debug:
            print(e.stdout.decode())
        raise



    print("✔️")

    # Append the paths for this newly built package
    prefix = f"{pkg['path']}/debian/ros-{os.environ['ROS_DISTRO']}-{pkg['name']}/opt/ros/ros1"
    object_path = f"{pkg['path']}/.obj-x86_64-linux-gnu"

    current = env.get("CMAKE_PREFIX_PATH", None)

    env["CMAKE_PREFIX_PATH"] = f"{prefix}"
    if current:
        env["CMAKE_PREFIX_PATH"] = f"{env['CMAKE_PREFIX_PATH']}:{current}"

    env["PATH"] = f"{prefix}/bin:" + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = f"{prefix}/lib:" + env.get("LD_LIBRARY_PATH", "")
    #env["LD_LIBRARY_PATH"] = f"{object_path}:" + env.get("LD_LIBRARY_PATH", "")
    env["PYTHONPATH"] = f"{prefix}/lib/python3/dist-packages:" + env.get("PYTHONPATH", "")

    if pkg["name"] == "ros_environment":
        env["ROS_DISTRO"] = ros_distro

    return env
"""

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



def resolve_dependencies(all_pkgs: dict, root_pkgs: list):
    """
    Given a dict of all discovered packages and a list of root package names,
    return a dict of packages that need to be built (root + dependencies).
    """
    to_build = set()
    visited = set()

    def visit(pkg_name):
        if pkg_name in visited:
            return
        visited.add(pkg_name)

        pkg_info = all_pkgs.get(pkg_name)
        if not pkg_info:
            # Package not found in workspace, might be a system dependency
            return

        to_build.add(pkg_name)

        # Recursively visit dependencies
        for dep in pkg_info.get('build_depends', []) + \
                   pkg_info.get('buildtool_depends', []) + \
                   pkg_info.get('run_depends', []):
            visit(dep)

    for root in root_pkgs:
        visit(root)

    return {name: all_pkgs[name] for name in to_build if name in all_pkgs}


def build_debian2(pkg: str, path: str, env):

    print(f"going to build package in {path}")

    # WHY ?!?!?!
    # Traceback (most recent call last):
    # File "/home/jprestwood/build-per-package/workspace/src/ros1/ros_environment/ros-o-ros_environment-348f78c/debian/tmp/build/ros1/ros_environment/catkin_generated/generate_cached_setup.py", line 22, in <module>
    #   code = generate_environment_script('/home/jprestwood/build-per-package/workspace/src/ros1/ros_environment/ros-o-ros_environment-348f78c/debian/tmp/build/ros1/ros_environment/devel/env.sh')
    # File "/home/jprestwood/build-per-package/workspace/src/ros1_install/lib/python3/dist-packages/catkin/environment_cache.py", line 63, in generate_environment_script
    #   env_after = ast.literal_eval(output.decode('utf8'))
    # File "/usr/lib/python3.10/ast.py", line 64, in literal_eval
    #   node_or_string = parse(node_or_string.lstrip(" \t"), mode='eval')
    # File "/usr/lib/python3.10/ast.py", line 50, in parse
    #   return compile(source, filename, mode, flags,
    # File "<unknown>", line 1
    #   ROS_DISTRO was set to 'ros1' before. Please make sure that the environment does not mix paths from different distributions.
    #              ^^^
    # SyntaxError: invalid syntax

    if pkg == "ros_environment" or pkg == "ros-environment":
        print("Unsetting ROS_DISTRO")
        ros_distro = env["ROS_DISTRO"]
        del env["ROS_DISTRO"]

    print(os.listdir(path))
    subprocess.run(
        ['fakeroot', 'debian/rules', 'binary'],
        cwd=path,
        check=True,
        env=env,
    )

    if pkg == "ros_environment" or pkg == "ros-environment":
        print("Setting ROS_DISTRO back")
        env["ROS_DISTRO"] = ros_distro

def build_debians(workspace: Path, ros_distro: str, locus_distro: str, os_distro: str, release_label: str, debug: bool = False, no_check: bool = False):
    print(f"building debians for packages under: {workspace}")

    distro_path = Path(f"{workspace}/src/{ros_distro}")
    recipe_path = Path(f"{workspace}/recipes/{locus_distro}-{os_distro}-{release_label}.yaml")

    if not distro_path.exists():
        raise Exception(f"Could not find workspace/distribution: {distro_path}")

    if not recipe_path.exists():
        raise Exception(f"Could not find recipe: {recipe_path}")

    recipe = yaml.safe_load(recipe_path.read_text())

    print(f"Building packages for recipe: {recipe['flavour']}")

    root_pkgs = recipe["distributions"][ros_distro]["root_packages"]

    # Packages to build
    pkgs = get_packages_in_workspace(distro_path, root_pkgs)


    sorted_pkgs = topological_sort_catkin_package_map(pkgs, root_pkgs)
    for pkg in sorted_pkgs:
        print(pkg.name)
        #print(pkg)


    #sorted_pkgs = topological_order(distro_path, pkgs)

    #for pkg_path, info in sorted_pkgs:
    #    print(info["name"])


    #print(sorted_pkgs)

    #return

    # All packages in workspace (ordered)
    #all_pkgs = find_packages(distro_path)


    # Build order list of packages

    #pkgs = resolve_dependencies(all_pkgs, root_pkgs)

    #sorted_pkgs = compute_build_order(all_pkgs, root_pkgs)

    #sorted_pkgs = find_packages(distro_path)

    #print(f"Collected {len(sorted_pkgs)} packages to build in order:")
    #for pkg in sorted_pkgs:
     #   print(pkg)

    ## Remove all debian folders
    #for debian_dir in distro_path.rglob("debian"):
    #    shutil.rmtree(debian_dir)

    for pkg in sorted_pkgs:
        if remove_duplicates_in_changelog(Path(pkg.filename).parent):
            print(f"Removed duplicates in {Path(pkg.filename).parent}")

    # Ensure we're running in a clean environment
    for var in ROS_ENV_VARS:
        if var in os.environ:
            del os.environ[var]

    #for var in ["LD_LIBRARY_PATH", "PKG_CONFIG_PATH", "PATH"]:
    #    paths = os.environ[var].split(":")
    #    for path in paths.copy():
    #        if "/opt/locusrobotics" in path:
    #            paths.remove(path)

    #    os.environ[var] = ":".join(paths)

    #env = os.environ.copy()

    #env["CMAKE_FIND_DEBUG_MODE"] = "1"

    #if no_check:
    #    env["DEB_BUILD_OPTIONS"] = "nocheck"

    #env["DEB_BUILD_OPTIONS"] = "parallel=2 " + env.get("DEB_BUILD_OPTIONS", "")
    env = os.environ.copy()

    env["DEB_BUILD_OPTIONS"] = "parallel=2 " + env.get("DEB_BUILD_OPTIONS", "")
    env["HOME"] = workspace


    print("Building packages in order:")
    #parallel_build(sorted_pkgs)
    for pkg in sorted_pkgs:
        # We will likely need to append each source to a CATKIN/CMAKE path variable
        # so that any dependent packages find what we already built.
        #env = build_debian(pkg, env, debug=debug, no_check=no_check)
        print(f"Building {pkg.name}")
        build_debian2(pkg.name, os.path.abspath(f"{Path(pkg.filename).parent}"), env)



def main():
    parser = argparse.ArgumentParser(description="Build per package debians")
    #parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--release-label', type=str, required=True)
    #parser.add_argument('--debian-version', type=str, required=True)
    parser.add_argument("--os-distro", type=str, required=True)
    parser.add_argument("--locus-distro", type=str, required=True)
    parser.add_argument("--ros-distro", type=str, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument("--debug", "-d", action="store_true")
    parser.add_argument("--no-check", "-n", action="store_true")
    args = parser.parse_args()

    sys.exit(build_debians(**vars(args)))


if __name__ == '__main__':
    main()
