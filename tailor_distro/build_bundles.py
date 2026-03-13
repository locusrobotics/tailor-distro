import argparse
import pathlib
import shutil
import subprocess
import jinja2

from concurrent import futures
from pathlib import Path

from debian_packager import fix_local_paths, package_debian

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


def create_environment_package(
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
    """

    # The directory tree where package install files will be copied
    staging = pathlib.Path("staging") / "environment"

    # Clean old staging
    shutil.rmtree(staging, ignore_errors=True)

    staging.mkdir()

    # Create the root dirs:
    ros1_root = staging / "opt" / organization / release_label / "ros1"
    ros2_root = staging / "opt" / organization / release_label / "ros2"

    ros1_root.mkdir(parents=True)
    ros2_root.mkdir(parents=True)

    # Re-create the root colcon workspace for each distribution. The reason this is
    # needed is because we're building in an isolated environment. But then during
    # packaging we actually "merge" everything back together. This results in a final
    # installable set of debians that appears like they were build with --merge-install.
    # The only way to do this is to re-generate the setup scripts with --merge-install
    # so everything sources correctly.
    colcon1 = subprocess.Popen(["colcon", "build", "--install-base", ros1_root, "--merge-install", "--packages-select"], env={})
    colcon2 = subprocess.Popen(["colcon", "build", "--install-base", ros2_root, "--merge-install", "--packages-select"], env={})

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

    deb_name = f"{organization}-environment-{release_label}"
    # TODO: Maybe a better way of determining versions for the bundles?
    deb_version = f"0.0.0+{build_date}{os_version}"

    package_debian(
        deb_name,
        deb_version,
        f"Meta-package for the {organization}-{release_label} environment",
        "James Prestwood <jprestwood@locusrobotics.com>",
        os_version,
        staging,
    )


def create_bundle_packages(
    graph: Graph,
    recipe: dict,
):
    ros1_list, _ = graph.build_list("ros1")
    ros2_list, _ = graph.build_list("ros2")

    for bundle, bundle_info in recipe["flavours"].items():
        source_depends = [f"{graph.organization}-environment-{graph.release_label} (= 0.0.0+{graph.build_date}{graph.os_version})"]
        for ros_dist, dist_info in bundle_info["distributions"].items():
            if ros_dist == "ros1":
                build_list = list(ros1_list.values())
            elif ros_dist == "ros2":
                build_list = list(ros2_list.values())
            else:
                raise Exception(f"Unhandled ROS distribution in recipe: {ros_dist}")

            pkg_list = [pkg.name for pkg in build_list]

            for pkg in dist_info["root_packages"]:
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
            source_depends
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
            create_environment_package,
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

        environment.result()
        bundles.result()


if __name__ == "__main__":
    main()
