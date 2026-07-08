import argparse
import pathlib
import subprocess
import os

from typing import List, Tuple

from . import YamlLoadAction
from .blossom import Graph, GraphPackage


def get_build_list(graph: Graph, ros_distro: str, recipe: dict | None = None) -> Tuple[List[GraphPackage], List[GraphPackage]]:
    if recipe:
        root_packages = recipe["distributions"][ros_distro]["root_packages"]
    else:
        root_packages = []

    packages, ignore = graph.build_list(ros_distro, root_packages)

    return list(packages.values()), list(ignore.values())


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
        "--ros-distro",
        required=True
    )
    parser.add_argument(
        "--force-packages",
        default=[],
        nargs="+"
    )
    parser.add_argument(
        "--no-clean",
        action="store_true"
    )

    args, unknown_args = parser.parse_known_args()

    graph = Graph.from_yaml(args.graph)

    # TODO: If we need to sort out specific packages to build, but the end goal
    # is to use colcon-cache for this.
    #build_list, ignore = get_build_list(graph, args.ros_distro)
    #build_packages = [pkg.name for pkg in build_list]

    install_path = (
        args.workspace
        / pathlib.Path("install")
        / pathlib.Path(args.ros_distro)
        / pathlib.Path("install")
    )
    build_base = (
        args.workspace
        / pathlib.Path("build")
        / pathlib.Path(args.ros_distro)
        / pathlib.Path("build")
    )
    base_path = args.workspace / pathlib.Path("src") / pathlib.Path(args.ros_distro)

    env = args.recipe["common"]["distributions"][args.ros_distro]["env"]

    env["ROS_PACKAGE_PATH"] = ""
    env["CMAKE_PREFIX_PATH"] = ""
    env["PYTHONPATH"] = ""
    env["AMENT_PREFIX_PATH"] = ""

    # Add the current distro's flat optinstall to AMENT_PREFIX_PATH unconditionally.
    # During the build, _do_package_debian copies each processed package into this
    # flat prefix. By the time ros1_bridge's factory generator runs, all prior
    # dependencies (e.g. nav_2d_msgs) have been copied here, making them
    # discoverable via ament_index_python even if they weren't rebuilt this run.
    # The underlay loop below handles the ros1 underlay separately.
    current_optinstall = pathlib.Path(
        f"optinstall/{graph.organization}/{graph.release_label}/{args.ros_distro}"
    ).absolute()
    prepend_env_path(env, "AMENT_PREFIX_PATH", str(current_optinstall))

    # Add source underlays. We may have both an installed distro (under /optinstall) and a
    # local workspace built prior.
    for underlay in args.recipe["common"]["distributions"][args.ros_distro].get("underlays", []):
        optinstall_prefix = pathlib.Path(
            f"optinstall/{graph.organization}/{graph.release_label}/{underlay}"
        ).absolute()
        prepend_env_path(env, "LD_LIBRARY_PATH", str(optinstall_prefix / "lib"))
        prepend_env_path(env, "PYTHONPATH", str(optinstall_prefix / "lib/python3/dist-packages"))
        prepend_env_path(env, "ROS_PACKAGE_PATH", str(optinstall_prefix / "share"))
        prepend_env_path(env, "PKG_CONFIG_PATH", str(optinstall_prefix / "lib/pkgconfig"))
        prepend_env_path(env, "CMAKE_PREFIX_PATH", str(optinstall_prefix))

    cxx_flags = args.recipe["common"]["cxx_flags"]
    cxx_standard = args.recipe["common"]["cxx_standard"]
    python_version = args.recipe["common"]["python_version"]

    for key, value in args.recipe["common"]["distributions"][args.ros_distro]["env"].items():
        env[key] = str(value)

    env["ROS_DISTRO_OVERRIDE"] = f"{graph.organization}-{graph.release_label}"
    env["CATKIN_INSTALL_INTO_PREFIX_ROOT"] = "0"
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = "4"
    env["RELEASE_LABEL"] = graph.release_label
    env["RELEASE_STAMP"] = graph.build_date

    print("Pre-build Environment:")
    for key, value in env.items():
        print(f"{key}={value}")

    # Construct the colcon command directly
    colcon_command = [
        "python3", "-m", "colcon", "package-debian",
        "--graph", str(args.graph),
        "--ros-version", args.ros_distro,
        "--parallel-workers", "4",
        "--packages-skip-cache-valid",
        "--base-paths", str(base_path),
        "--build-base", str(build_base),
        "--install-base", str(install_path),
        "--cmake-args",
        f"-DCMAKE_CXX_FLAGS={' '.join(cxx_flags)}",
        f"-DCMAKE_CXX_STANDARD={cxx_standard}",
        "-DCMAKE_CXX_STANDARD_REQUIRED=ON",
        "-DCMAKE_CXX_EXTENSIONS=ON",
        "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        f"-DPYTHON_EXECUTABLE=/usr/bin/python{python_version}",
        "-DCMAKE_VERBOSE_MAKEFILE=ON",
        "-DCHECK_FOR_UPDATES=OFF",
        "-DCMAKE_INSTALL_SYMLINK_SUPPORTED=FALSE",
        "-G", "Ninja",
        "--ament-cmake-args",
        "-DBUILD_TESTING=OFF",
        "--catkin-cmake-args",
        "-DCATKIN_SKIP_TESTING=1",
        "--catkin-skip-building-tests",
        "--event-handlers", "console_cohesion+",
    ]

    # Add unknown args if any
    colcon_command.extend(unknown_args)

    merged_env = {**os.environ, **{k: str(v) for k, v in env.items()}}

    # For path-like variables, prepend custom values rather than replacing,
    # so that installed package paths (e.g. colcon plugins) remain discoverable.
    for path_var in ("PYTHONPATH", "LD_LIBRARY_PATH", "CMAKE_PREFIX_PATH", "ROS_PACKAGE_PATH", "PKG_CONFIG_PATH", "AMENT_PREFIX_PATH"):
        if path_var in env and os.environ.get(path_var):
            custom = str(env[path_var])
            base = os.environ[path_var]
            merged_env[path_var] = f"{custom}:{base}" if custom else base

    build_proc = subprocess.Popen(
        colcon_command,
        env=merged_env
    )

    exit(build_proc.wait())

if __name__ == "__main__":
    main()
