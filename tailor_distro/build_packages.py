import argparse
import pathlib
import subprocess
import jinja2
import shutil
import re
import os

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from . import YamlLoadAction
from .blossom import Graph, GraphPackage


PACKAGING_THREADS = 4


def get_build_list(graph: Graph, recipe: dict | None = None) -> Tuple[List[GraphPackage], List[GraphPackage]]:
    if recipe:
        root_packages = recipe["distributions"][graph.distribution]["root_packages"]
    else:
        root_packages = []

    packages, ignore = graph.build_list(root_packages)

    return list(packages.values()), list(ignore.values())


# Taken from bloom to format the description:
# https://github.com/ros-infrastructure/bloom/blob/master/bloom/generators/debian/generator.py
def debianize_string(value):
    markup_remover = re.compile(r'<.*?>')
    value = markup_remover.sub('', value)
    value = re.sub(r'\s+', ' ', value)
    value = value.strip()
    return value


def format_description(value):
    """
    Format proper <synopsis, long desc> string following Debian control file
    formatting rules. Treat first line in given string as synopsis, everything
    else as a single, large paragraph.

    Future extensions of this function could convert embedded newlines and / or
    html into paragraphs in the Description field.

    https://www.debian.org/doc/debian-policy/ch-controlfields.html#s-f-Description
    """
    value = debianize_string(value)
    # NOTE: bit naive, only works for 'properly formatted' pkg descriptions (ie:
    #       'Text. Text'). Extra space to avoid splitting on arbitrary sequences
    #       of characters broken up by dots (version nrs fi).
    parts = value.split('. ', 1)
    if len(parts) == 1 or len(parts[1]) == 0:
        # most likely single line description
        return value
    # format according to rules in linked field documentation
    return u"{0}.\n {1}".format(parts[0], parts[1].strip())


def package_debian(
    name: str, install_path: pathlib.Path, graph: Graph, build_list: List[GraphPackage]
):
    if not (install_path / pathlib.Path(name)).exists():
        print(f"Package {name} was not built, ignoring")
        return

    # The directory tree where package install files will be copied
    staging = pathlib.Path("staging") / name

    # Clean old staging
    shutil.rmtree(staging, ignore_errors=True)

    # Packaging requires the folder structure to match where the debian will be
    # installed. Colcon isn't capable of this when building many packages, so
    # we create that structure here and copy the tree.
    final_prefix = (
        staging
        / "opt"
        / graph.organization
        / graph.release_label
        / graph.distribution
    )
    final_prefix.mkdir(parents=True)

    ignore_patterns = [".catkin"]

    # TODO: Remove this once the lokimon/lokimon_bots package is fixed
    if name == "lokimon_bots":
        ignore_patterns += "__init__.py"

    # Copy workspace-installed files into the final prefix
    shutil.copytree(
        install_path / pathlib.Path(name),
        final_prefix,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*ignore_patterns)
    )

    # Create DEBIAN control directory
    debian_dir = staging / "DEBIAN"
    debian_dir.mkdir()

    package = graph.packages[name]

    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )

    pkg_list = [pkg.name for pkg in build_list]

    source_depends = []
    for dep in package.source_depends:
        dep_pkg = graph.packages[dep]

        if dep in pkg_list:
            # If the dependency was built in this run we can generate the debian
            # version based on the build date.
            source_depends.append(
                f"{dep_pkg.debian_name(*graph.debian_info)} (= {dep_pkg.debian_version(graph.build_date)})"
            )
        elif dep_pkg.apt_candidate_version:
            # Otherwise add the version that has been built prior
            source_depends.append(
                f"{dep_pkg.debian_name(*graph.debian_info)} (= {dep_pkg.apt_candidate_version})"
            )
        else:
            raise Exception(f"Package {dep} is not in the build list or in the APT mirror!")

    deb_name = package.debian_name(*graph.debian_info)
    deb_version = package.debian_version(graph.build_date)

    context = {
        "debian_name": deb_name,
        "run_depends": package.apt_depends + source_depends,
        "description": format_description(package.description),
        "debian_version": deb_version,
        "maintainer": package.maintainers,
    }

    control = env.get_template("control.j2")
    stream = control.stream(**context)
    stream.dump(str(debian_dir / "control"))

    p = subprocess.run(
        [
            "dpkg-deb",
            "--build",
            staging,
            f"{deb_name}_{deb_version}_amd64_{graph.os_version}.deb",
        ]
    )
    if p.returncode != 0:
        print(f"Failed to package {name}")
        print((debian_dir / "control").read_text())


def start_packaging(build_proc: subprocess.Popen, graph: Graph, build_list: List[GraphPackage], workspace: pathlib.Path, install_path: pathlib.Path):
    pathlib.Path.mkdir(workspace / "debians", exist_ok=True)

    futures = []
    errors = []

    with ThreadPoolExecutor(max_workers=PACKAGING_THREADS) as executor:
        for line in build_proc.stdout:
            line = line.decode("utf-8").strip()
            # Print so we get the normal build output
            print(line)

            if "Finished <<< " in line:
                package = line.split(" ")[2]
                futures.append(executor.submit(package_debian, package, install_path, graph, build_list))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                errors.append(e)

    if errors:
        raise Exception(f"Errors encountered during packaging: {errors}")


def run_with_sources(command, sources, env):
    lines = []
    for src in sources:
        lines.append(f'source "{src}"')

    script = "\n".join(lines) + '\nexec "$@"'

    print(f"RUNNING:\n{['bash', '-c', script, 'bash', *command]}")

    return subprocess.Popen(
        ["bash", "-c", script, "bash", *command],
        env=env,
        stdout=subprocess.PIPE
    )


def prepend_env_path(env: dict, key: str, value: str):
    if key in env:
        env[key] = f"{value}:{env[key]}"
    else:
        env[key] = value

    return env

def main():
    parser = argparse.ArgumentParser(
        description="Build ROS packages that aren't already built"
    )
    parser.add_argument(
        "--recipe",
        action=YamlLoadAction,
        required=True
    )
    parser.add_argument(
        "--graph",
        type=pathlib.Path,
        required=True
    )
    parser.add_argument(
        "--workspace",
        type=pathlib.Path,
        required=True
    )
    parser.add_argument(
        "--force-packages",
        default=[],
        nargs="+"
    )
    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)

    build_list, ignore = get_build_list(graph)

    source_path = (
        args.workspace /
        pathlib.Path("src") /
        pathlib.Path(graph.distribution)
    )

    # Ignore packages that have a debian already. This avoids the need to pass
    # a full list to colcon which will frequently exceeds the argument maximum
    for package in ignore:
        if package.name in args.force_packages:
            continue
        print(f"Ignoring {package}")
        (source_path / pathlib.Path(package.path) / "COLCON_IGNORE").touch()

    install_path = (
        args.workspace
        / pathlib.Path("install")
        / pathlib.Path(graph.distribution)
        / pathlib.Path("install")
    )
    build_base = (
        args.workspace
        / pathlib.Path("build")
        / pathlib.Path(graph.distribution)
        / pathlib.Path("build")
    )
    base_path = args.workspace / pathlib.Path("src") / pathlib.Path(graph.distribution)

    sources = []
    underlay_paths = []

    bundle_prefix = pathlib.Path(f"/opt/{graph.organization}/{graph.release_label}")

    # This would exist from installing pre-existing debians
    partial_bundle = bundle_prefix / graph.distribution

    # Source underlays. We may have both an installed distro (under /opt) and a
    # local workspace built prior.
    underlays = args.recipe["common"]["distributions"][graph.distribution].get("underlays", [])
    for underlay in underlays:
        bundle_underlay_path = bundle_prefix / f"{underlay}/setup.bash"
        if bundle_underlay_path.exists():
            underlay_paths.append(str(bundle_underlay_path))

        # Don't source the local underlay workspace, due to how colcon builds it ends up
        # adding hundreds of package paths, which explode the env.
        local_underlay_path = args.workspace / f"install/{underlay}/install/setup.bash"
        if local_underlay_path.exists():
            underlay_paths.append(str(args.workspace / f"install/{underlay}/install"))

    # TODO: Add remaining logic that currently exists within the rules.j2 template
    command = [
        "colcon",
        "build",
        "--base-paths",
        base_path,
        "--install-base",
        install_path,
        "--build-base",
        build_base
    ]

    cxx_flags = " ".join(args.recipe["common"]["cxx_flags"])
    cxx_standard = args.recipe["common"]["cxx_standard"]
    python_version = args.recipe["common"]["python_version"]

    command.extend([
        "--cmake-args",
        f"-DCMAKE_CXX_FLAGS={cxx_flags}",
        f"-DCMAKE_CXX_STANDARD={cxx_standard}",
        "-DCMAKE_CXX_STANDARD_REQUIRED=ON",
        "-DCMAKE_CXX_EXTENSIONS=ON",
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        f"-DPYTHON_EXECUTABLE=/usr/bin/python{python_version}",
        "--ament-cmake-args", "-DBUILD_TESTING=OFF",
        "--catkin-cmake-args", "-DCATKIN_SKIP_TESTING=1",
        "--catkin-skip-building-tests",
        "--catkin-skip-building-tests",
        "--event-handlers", "console_cohesion+"
    ])

    env = os.environ.copy()

    # Clean the ROS env paths
    for key in ["ROS_PACKAGE_PATH", "PYTHONPATH", "CMAKE_PREFIX_PATH", "AMENT_PREFIX_PATH"]:
        if key in env:
            del env[key]

    # After building ROS1 the ROS_PACKAGE_PATH includes a path for every
    # individual package which ends up exploding the env and generally fails to
    # build ROS2. For ROS1 itself we can just clear this entirely. For ROS2
    # we can get away with setting it to point to the workspace.
    #
    # TODO: We may have other env vars that need sanitation...
    if partial_bundle.exists():
        if graph.distribution == "ros1":
            env = prepend_env_path(env, "ROS_PACKAGE_PATH", str(partial_bundle))
            env = prepend_env_path(env, "CMAKE_PREFIX_PATH", str(partial_bundle))
            env = prepend_env_path(env, "PYTHONPATH", str(partial_bundle / pathlib.Path("lib/python3/dist-packages")))
        elif graph.distribution == "ros2":
            env = prepend_env_path(env, "AMENT_PREFIX_PATH", str(partial_bundle))

    for path in underlay_paths:
        env = prepend_env_path(env, "ROS_PACKAGE_PATH", os.path.abspath(path))
        env = prepend_env_path(env, "CMAKE_PREFIX_PATH", os.path.abspath(path))

    for key, value in args.recipe["common"]["distributions"][graph.distribution]["env"].items():
        env[key] = str(value)

    env["ROS_DISTRO_OVERRIDE"] = f"{graph.organization}-{graph.release_label}"

    print("Pre-build Environment:")
    for key, value in env.items():
        print(f"{key}={value}")

    build_proc = run_with_sources(command, sources, env)

    start_packaging(build_proc, graph, build_list, args.workspace, install_path)

    #if p.returncode != 0:
    #    print("colcon failed to build packages, continuing to packaging what was built")




if __name__ == "__main__":
    main()
