import argparse
import pathlib
import shutil
import subprocess
import jinja2
import os

from concurrent import futures
from pathlib import Path

from debian_packager import (
    build_debian_info,
    build_package_name,
    build_package_version,
    fix_local_paths,
    package_debian,
    environment_package_name,
    environment_package_version
)

from . import YamlLoadAction
from .blossom import Graph


TEMPLATE_SUFFIX = '.j2'


def create_compat_catkin_files(staging_dir: Path):
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_distro", "debian_templates/compat_catkin_tools"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )

    for template_name in env.list_templates():
        if not template_name.endswith(TEMPLATE_SUFFIX):
            continue

        output = staging_dir / template_name[:-len(TEMPLATE_SUFFIX)]
        control = env.get_template(template_name)
        stream = control.stream()
        stream.dump(str(output))

        os.chmod(output, 0o755)


def create_environment_packages(
    organization: str,
    release_label: str,
    os_version: str,
    build_date: str,
):
    """
    Bundles the setup/env files at the root of the ROS distribution (e.g. setup.sh)
    With per-package builds each bundle metapackage will depend on a single
    environment package that populates the setup files. This is in order to support
    installing multiple bundles which would end up conflicting on these common
    files.

    This is done with the following steps:

    1. Create an empty colcon workspace via colcon build, but pass --merge-install
       (contrary to what you would expect since we built packages without --merge-install)
       The workspaces (ros1/ros2) are build directly in the staging directory.
    2. Create workaround compatibility scripts for ROS1
    3. Replace local paths with the expected install dirs under /opt
    4. Package both ros1 and ros2 workspaces into a single "environment" debian.
    """

    # The directory tree where package install files will be copied
    ros1_staging = pathlib.Path("staging") / "ros1_environment"
    ros2_staging = pathlib.Path("staging") / "ros2_environment"


    # Clean old staging
    shutil.rmtree(ros1_staging, ignore_errors=True)
    shutil.rmtree(ros2_staging, ignore_errors=True)

    ros1_staging.mkdir()
    ros2_staging.mkdir()

    # Create the root dirs:
    ros1_root = ros1_staging / "opt" / organization / release_label / "ros1"
    ros2_root = ros2_staging / "opt" / organization / release_label / "ros2"

    ros1_root.mkdir(parents=True)
    ros2_root.mkdir(parents=True)

    # Re-create the root colcon workspace for each distribution. The reason this is
    # needed is because we're building in an isolated environment. But then during
    # packaging we actually "merge" everything back together. This results in a final
    # installable set of debians that appears like they were build with --merge-install.
    # The only way to do this is to re-generate the setup scripts with --merge-install
    # so everything sources correctly.
    colcon1 = subprocess.Popen(
        [
            "colcon",
            "build",
            "--install-base", ros1_root,
            "--base-paths", ros1_root,
            "--merge-install",
            "--packages-select"
        ],
        env={}
    )

    # For ROS2 we pass in the ROS1 prefix which will let colcon chain the workspaces
    # together. This isn't strictly needed, but maintiains the existing behavior
    # where if you source ROS2 it also sources ROS1 for you.
    colcon2 = subprocess.Popen(
        [
            "colcon",
            "build",
            "--install-base", ros2_root,
            "--base-paths", ros2_root,
            "--merge-install",
            "--packages-select"
        ],
        env={
            "COLCON_PREFIX_PATH": ros1_root.resolve()
        }
    )

    colcon1.wait()
    colcon2.wait()

    # A merged install creates a single .catkin at the root of the workspace but
    # an isolated install creates one for individual packages. We can't package
    # .catkin with individual packages as they would conflict, so package it here.
    (ros1_root / ".catkin").touch()
    (ros2_root / ".catkin").touch()

    # Workaround colcon not creating env.sh https://github.com/colcon/colcon-ros/issues/16
    create_compat_catkin_files(ros1_root)

    # Replace the local paths with the correct /opt paths
    fix_local_paths(organization, release_label, "ros1", ros1_root, ros1_root.resolve())
    fix_local_paths(organization, release_label, "ros2", ros2_root, ros2_root.resolve())

    # Special case to fix the chained prefix for ROS2, which points to ROS1. We're
    # replacing paths pointing to ROS1, but within the ROS2 workspace.
    fix_local_paths(organization, release_label, "ros1", ros2_root, ros1_root.resolve())

    package_debian(
        environment_package_name(organization, release_label, "ros1"),
        environment_package_version(build_date, os_version),
        f"Meta-package for the {organization}-{release_label} ROS1 environment",
        "James Prestwood <jprestwood@locusrobotics.com>",
        os_version,
        ros1_staging,
    )

    package_debian(
        environment_package_name(organization, release_label, "ros2"),
        environment_package_version(build_date, os_version),
        f"Meta-package for the {organization}-{release_label} ROS2 environment",
        "James Prestwood <jprestwood@locusrobotics.com>",
        os_version,
        ros2_staging,
    )


def create_build_tools_packages(graph: Graph):
    for ros_dist in ["ros1", "ros2"]:
        # Gather build depends from all packages
        build_depends = set()

        for pkg in graph.packages[ros_dist].values():
            # Apt dependency names can be used as-is
            build_depends.update(pkg.build_depends(types=["apt"]))

            # Source dependencies need to be converted to their debian equivalents with versions.
            for dep in pkg.build_depends(types=["source"]):
                dep_pkg = graph.packages[ros_dist][dep]
                build_depends.add(
                    f"{dep_pkg.debian_name(*graph.debian_info)} (= {dep_pkg.debian_version(graph.build_date)})"
                )

        staging_dir = pathlib.Path("staging") / f"{ros_dist}_build_tools"

        # Clean old staging
        shutil.rmtree(staging_dir, ignore_errors=True)

        staging_dir.mkdir()

        deb_name = build_package_name(graph.organization, graph.release_label, ros_dist)
        deb_version = build_package_version(graph.build_date, graph.os_version)

        package_debian(
            deb_name,
            deb_version,
            f"Meta-package for the {graph.organization}-{graph.release_label} {ros_dist} build tools bundle",
            "James Prestwood <jprestwood@locusrobotics.com>",
            graph.os_version,
            staging_dir,
            run_depends=list(build_depends),
        )

def create_bundle_packages(
    graph: Graph,
    recipe: dict,
):
    """
    Creates meta-packages for each bundle flavor. The work here is pulling out all the
    root packages for ros1/ros2, and including those as dependencies when packaging
    the debians.
    """
    ros1_list, _ = graph.build_list("ros1")
    ros2_list, _ = graph.build_list("ros2")

    for bundle, bundle_info in recipe["flavours"].items():
        source_depends = []
        for ros_dist, dist_info in bundle_info["distributions"].items():
            if ros_dist == "ros1":
                build_list = list(ros1_list.values())
            elif ros_dist == "ros2":
                build_list = list(ros2_list.values())
            else:
                raise Exception(f"Unhandled ROS distribution in recipe: {ros_dist}")

            pkg_list = [pkg.name for pkg in build_list]

            # If there are no root_packages specified in the recipe, we assume all packages in the
            # graph for that distribution are root packages and should be included as dependencies.
            # This is only true for dev/test bundles and for these bundles we also want to include
            # all build dependencies via the build-tools bundle
            if dist_info["root_packages"] == []:
                root_packages = graph.packages[ros_dist].keys()
                source_depends.append(
                    build_debian_info(
                        graph.organization,
                        graph.release_label,
                        ros_dist,
                        graph.build_date,
                        graph.os_version
                    )
                )
            else:
                root_packages = dist_info["root_packages"]

            for pkg in root_packages:
                dep_pkg = graph.packages[ros_dist][pkg]
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

        # For convenience add the build-tools bundle as a build depend for all bundles. This allows
        # us to save a lot of space in images by not including build tools, but for workspace
        # overlays we can still install the build tools with:
        # apt build-dep <bundle>
        build_depends = [
            f"{build_package_name(graph.organization, graph.release_label, 'ros1')} (= {build_package_version(graph.build_date, graph.os_version)})",
            f"{build_package_name(graph.organization, graph.release_label, 'ros2')} (= {build_package_version(graph.build_date, graph.os_version)})",
        ]

        deb_name = f"{graph.organization}-{bundle}-{graph.release_label}"
        # TODO: Maybe a better way of determining versions for the bundles?
        deb_version = f"0.0.0+{graph.build_date}{graph.os_version}"

        package_debian(
            deb_name,
            deb_version,
            f"Meta-package for the {graph.organization}-{graph.release_label} {bundle} bundle",
            "James Prestwood <jprestwood@locusrobotics.com>",
            graph.os_version,
            staging,
            run_depends=source_depends,
            build_depends=build_depends
        )


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
        "--graph",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True
    )
    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)

    with futures.ThreadPoolExecutor(max_workers=2) as executor:
        environment = executor.submit(
            create_environment_packages,
            graph.organization,
            graph.release_label,
            graph.os_version,
            graph.build_date
        )
        bundles = executor.submit(
            create_bundle_packages,
            graph,
            args.recipe
        )
        build_tools = executor.submit(
            create_build_tools_packages,
            graph
        )

        environment.result()
        bundles.result()
        build_tools.result()


if __name__ == "__main__":
    main()
