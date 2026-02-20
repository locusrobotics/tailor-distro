import argparse
import pathlib
import subprocess
import jinja2
import shutil
import os

from typing import List
from pathlib import Path

from . import YamlLoadAction
from .blossom import Graph


def copy_distro_install(staging: Path, path: Path, organization: str, release_label: str, ros_dist: str):
    if not path.exists():
        return

    final_prefix = (
        staging
        / "opt"
        / organization
        / release_label
        / ros_dist
    )
    final_prefix.mkdir(parents=True)
    for file in os.listdir(path):
        full_path = path / pathlib.Path(file)
        if full_path.is_dir():
            continue

        shutil.copy(full_path, final_prefix)


def create_bundle_packages(graphs: List[Graph], recipe: dict, workspace: Path):
    # Global values
    organization = recipe["common"]["organization"]
    # Since we run the OS versions in different pipelines there should only be
    # a single version per set of graphs
    os_version = None
    # Same with release label, they should never differ
    release_label = None

    for graph in graphs:
        if os_version is None:
            os_version = graph.os_version
        elif os_version != graph.os_version:
            raise Exception("Graphs passed in use differnt OS versions!")

        if release_label is None:
            release_label = graph.release_label
        elif release_label != graph.release_label:
            raise Exception("Graphs passed in use differnt OS versions!")

        if graph.distribution == "ros1":
            ros1_graph = graph
            ros1_list, _ = graph.build_list()
            ros1_install_path = (
                workspace
                / pathlib.Path("install")
                / pathlib.Path(graph.distribution)
                / pathlib.Path("install")
            )
        elif graph.distribution == "ros2":
            ros2_graph = graph
            ros2_list, _ = graph.build_list()
            ros2_install_path = (
                workspace
                / pathlib.Path("install")
                / pathlib.Path(graph.distribution)
                / pathlib.Path("install")
            )
        else:
            raise Exception(f"Unhandled ROS distribution in graph: {graph.distribution}")

    for bundle, bundle_info in recipe["flavours"].items():
        source_depends = []
        for ros_dist, dist_info in bundle_info["distributions"].items():
            if ros_dist == "ros1":
                build_list = list(ros1_list.values())
                graph = ros1_graph
                print("Setting graph to ros1")
            elif ros_dist == "ros2":
                build_list = list(ros2_list.values())
                graph = ros2_graph
            else:
                raise Exception(f"Unhandled ROS distribution in recipe: {ros_dist}")

            pkg_list = [pkg.name for pkg in build_list]

            print(f"Root packages for {ros_dist}:")
            for pkg in dist_info["root_packages"]:
                print(graph.distribution)
                dep_pkg = graph.packages[pkg]
                print(f"    {pkg}")
                if pkg in pkg_list:
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
                    raise Exception(f"Package {pkg} is not in the build list or in the APT mirror!")

        print(f"Creating debian templates for {bundle}. Dependencies: {source_depends}")

        # The directory tree where package install files will be copied
        staging = pathlib.Path("staging") / bundle

        # Clean old staging
        shutil.rmtree(staging, ignore_errors=True)

        staging.mkdir()

        # Create DEBIAN control directory
        debian_dir = staging / "DEBIAN"
        debian_dir.mkdir()

        # Packaging requires the folder structure to match where the debian will be
        # installed. Colcon isn't capable of this when building many packages, so
        # we create that structure here and copy the tree.
        copy_distro_install(staging, ros1_install_path, organization, release_label, "ros1")
        copy_distro_install(staging, ros2_install_path, organization, release_label, "ros2")

        env = jinja2.Environment(
            loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
        )

        deb_name = f"{graph.organization}-{bundle}-{graph.release_label}"
        # TODO: Maybe a better way of determining versions for the bundles?
        deb_version = f"0.0.0+{graph.build_date}{os_version}"

        context = {
            "debian_name": deb_name,
            "run_depends": source_depends,
            "description": f"Meta-package for the {graph.organization}-{graph.release_label} {bundle} bundle",
            "debian_version": deb_version,
            "maintainer": "James Prestwood <jprestwood@locusrobotics.com>",
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
            print(f"Failed to package {bundle}")
            print((debian_dir / "control").read_text())

def main():
    parser = argparse.ArgumentParser(
        description="Build bundle metapackages"
    )
    parser.add_argument(
        "--recipe",
        action=YamlLoadAction,
        required=True
    )
    parser.add_argument(
        "--graphs",
        type=Path,
        required=True,
        nargs="+"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True
    )
    args = parser.parse_args()

    graphs = [Graph.from_yaml(path) for path in args.graphs]

    create_bundle_packages(graphs, args.recipe, args.workspace)


if __name__ == "__main__":
    main()
