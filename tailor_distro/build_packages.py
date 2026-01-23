import argparse
import pathlib
import subprocess
import jinja2
import shutil

from typing import List

from . import YamlLoadAction
from .blossom import Graph


def get_build_list(graph: Graph, recipe: dict | None = None):
    if recipe:
        root_packages = recipe["distributions"][graph.distribution]["root_packages"]
    else:
        root_packages = []

    packages, _ = graph.build_list(root_packages)

    return list(packages.keys())


def package_debian(
    name: str, install_path: pathlib.Path, graph: Graph, build_list: List[str]
):
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
        / name
    )
    final_prefix.mkdir(parents=True)

    # Copy workspace-installed files into the final prefix
    shutil.copytree(install_path / pathlib.Path(name), final_prefix, dirs_exist_ok=True)

    # Create DEBIAN control directory
    debian_dir = staging / "DEBIAN"
    debian_dir.mkdir()

    package = graph.packages[name]

    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )

    source_depends = []
    for dep in package.source_depends:
        dep_pkg = graph.packages[dep]

        if dep in build_list:
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
        "description": package.description,
        "debian_version": deb_version,
        "maintainer": package.maintainers,
    }

    control = env.get_template("control.j2")
    stream = control.stream(**context)
    stream.dump(str(debian_dir / "control"))

    subprocess.run(
        [
            "dpkg-deb",
            "--build",
            staging,
            f"{deb_name}_{deb_version}_amd64_{graph.os_version}.deb",
        ]
    )


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
    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)

    build_list = get_build_list(graph)

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

    # TODO: Add remaining logic that currently exists within the rules.j2 template
    command = [
        "colcon",
        "build",
        "--base-paths",
        base_path,
        "--install-base",
        install_path,
        "--build-base",
        build_base,
        "--packages-select",
    ]

    # Extend with packages we're building
    command.extend(build_list)

    cxx_flags = " ".join(args.recipe["common"]["cxx_flags"])
    cxx_standard = args.recipe["common"]["cxx_standard"]
    python_version = args.recipe["common"]["python_version"]

    command.extend([
        "--cmake-args",
        f"-DCMAKE_CXX_FLAGS='{cxx_flags}'",
        f"-DCMAKE_CXX_STANDARD='{cxx_standard}'",
        "-DCMAKE_CXX_STANDARD_REQUIRED='ON'",
        "-DCMAKE_CXX_EXTENSIONS='ON'",
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        f"-DPYTHON_EXECUTABLE=/usr/bin/python{python_version}",
        "--ament-cmake-args -DBUILD_TESTING=OFF",
        "--catkin-cmake-args -DCATKIN_SKIP_TESTING=1",
        "--catkin-skip-building-tests"
    ])

    subprocess.run(command)

    pathlib.Path.mkdir(args.workspace / "debians", exist_ok=True)

    for name in build_list:
        package_debian(name, install_path, graph, build_list)


if __name__ == "__main__":
    main()
