import argparse
import os
import pathlib
import pwd
import shutil
import subprocess
import sys

from typing import List, Tuple


def _source_setup(setup_script: pathlib.Path, base_env: dict) -> dict:
    """Source a colcon setup.bash in a clean shell and return the resulting environment."""
    if not setup_script.exists():
        return dict(base_env)
    result = subprocess.run(
        ["bash", "--norc", "--noprofile", "-c",
         f"source '{setup_script}' 2>/dev/null; env"],
        capture_output=True, text=True, env=base_env,
    )
    if result.returncode != 0:
        return dict(base_env)
    captured = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            captured[k] = v
    return captured

from . import YamlLoadAction
from .blossom import Graph, GraphPackage


def get_build_list(graph: Graph, ros_distro: str, recipe: dict | None = None, rebuild_all: bool = False) -> Tuple[List[GraphPackage], List[GraphPackage]]:
    if recipe:
        root_packages = recipe["distributions"][ros_distro]["root_packages"]
    else:
        root_packages = []

    packages, ignore = graph.build_list(ros_distro, root_packages, rebuild_all=rebuild_all)

    return list(packages.values()), list(ignore.values())


def prepend_env_path(env: dict, key: str, value: str):
    if key in env and env[key]:
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
    parser.add_argument(
        "--rebuild-all",
        action="store_true"
    )

    args, unknown_args = parser.parse_known_args()

    # Normalize incoming paths so environment variables are deterministic
    # regardless of the caller's current working directory.
    args.workspace = args.workspace.resolve()
    args.graph = args.graph.resolve()

    graph = Graph.from_yaml(args.graph)

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
    optinstall_root = (
        args.workspace
        / pathlib.Path("..")
        / pathlib.Path("optinstall")
        / pathlib.Path(graph.organization)
        / pathlib.Path(graph.release_label)
    ).resolve()
    current_optinstall_prefix = optinstall_root / pathlib.Path(args.ros_distro)

    packages_to_build, apt_packages = get_build_list(graph, args.ros_distro, rebuild_all=args.rebuild_all)

    if apt_packages:
        print(f"[APT] Installing {len(apt_packages)} unchanged packages via apt...")
        apt_names = [
            f"{pkg.debian_name(graph.organization, graph.release_label)}={pkg.apt_candidate_version}"
            for pkg in apt_packages
            if pkg.apt_candidate_version
        ]
        if apt_names:
            subprocess.run(["sudo", "-E", "apt-get", "update", "-qq"], check=False)
            apt_result = subprocess.run(
                ["sudo", "-E", "apt-get", "install", "-y", "--no-install-recommends"] + apt_names,
                check=False
            )
            if apt_result.returncode != 0:
                print("[APT] apt-get install failed, falling back to full build")
                apt_packages = []

    cxx_flags = args.recipe["common"]["cxx_flags"]
    cxx_standard = args.recipe["common"]["cxx_standard"]
    python_version = args.recipe["common"]["python_version"]

    venv_bin = str(pathlib.Path(sys.executable).parent)
    rustup_home = os.environ.get("RUSTUP_HOME", "/opt/rust/rustup")
    cargo_home = os.environ.get("CARGO_HOME", "/opt/rust/cargo")
    cargo_bin = str(pathlib.Path(cargo_home) / "bin")
    real_home = pwd.getpwuid(os.getuid()).pw_dir

    # Minimal base: no host env leakage.
    base_env = {
        "PATH": f"{venv_bin}:{cargo_bin}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": real_home,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "RUSTUP_HOME": rustup_home,
        "CARGO_HOME": cargo_home,
        "RUSTUP_INIT_SKIP_PATH_CHECK": "yes",
    }

    ros1_opt = pathlib.Path(f"/opt/{graph.organization}/{graph.release_label}/ros1")
    ros2_opt = pathlib.Path(f"/opt/{graph.organization}/{graph.release_label}/ros2")

    # Source installed underlays: ros1 always, then ros2 on top for ros2 builds.
    env = _source_setup(ros1_opt / "setup.bash", base_env)
    if args.ros_distro == "ros2":
        env = _source_setup(ros2_opt / "setup.bash", env)

    # Prepend workspace-built and optinstall paths so they shadow /opt packages.
    current_workspace_prefix = install_path
    for prefix in (current_optinstall_prefix, current_workspace_prefix):
        prepend_env_path(env, "LD_LIBRARY_PATH", str(prefix / "lib"))
        prepend_env_path(env, "PYTHONPATH", str(prefix / "lib/python3/dist-packages"))
        prepend_env_path(env, "PKG_CONFIG_PATH", str(prefix / "lib/pkgconfig"))
        prepend_env_path(env, "CMAKE_PREFIX_PATH", str(prefix))
        if args.ros_distro == "ros2":
            prepend_env_path(env, "AMENT_PREFIX_PATH", str(prefix))
        elif args.ros_distro == "ros1":
            prepend_env_path(env, "ROS_PACKAGE_PATH", str(prefix / "share"))

    # Add any additional workspace-built underlay distros (e.g. ros1 built in this run for ros2).
    for underlay in args.recipe["common"]["distributions"][args.ros_distro].get("underlays", []):
        ws_underlay = args.workspace / "install" / underlay / "install"
        opt_underlay = optinstall_root / underlay
        for prefix in (opt_underlay, ws_underlay):
            prepend_env_path(env, "LD_LIBRARY_PATH", str(prefix / "lib"))
            prepend_env_path(env, "PYTHONPATH", str(prefix / "lib/python3/dist-packages"))
            prepend_env_path(env, "PKG_CONFIG_PATH", str(prefix / "lib/pkgconfig"))
            prepend_env_path(env, "CMAKE_PREFIX_PATH", str(prefix))
            if underlay == "ros1":
                prepend_env_path(env, "ROS_PACKAGE_PATH", str(prefix / "share"))
            elif underlay == "ros2":
                prepend_env_path(env, "AMENT_PREFIX_PATH", str(prefix))

    # Build-specific variables (applied last so they cannot be overwritten by setup scripts).
    env.update({k: str(v) for k, v in args.recipe["common"]["distributions"][args.ros_distro]["env"].items()})
    env["ROS_DISTRO_OVERRIDE"] = f"{graph.organization}-{graph.release_label}"
    env["CATKIN_INSTALL_INTO_PREFIX_ROOT"] = "0"
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = "4"
    env["MAKEFLAGS"] = "-j 2"
    env["RELEASE_LABEL"] = graph.release_label
    env["RELEASE_STAMP"] = graph.build_date

    # Construct the colcon command directly
    colcon_command = [
        sys.executable, "-m", "colcon", "package-debian",
        "--graph", str(args.graph),
        "--ros-version", args.ros_distro,
        "--parallel-workers", "4",

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

    if apt_packages:
        colcon_command.append("--skip-apt-available")

    # Add unknown args if any
    colcon_command.extend(unknown_args)

    print("Pre-build Environment:")
    for key, value in env.items():
        print(f"{key}={value}")

    # Print the resolved Cargo path from the build environment for debugging
    # toolchain mismatches in CI containers.
    print(f"Resolved cargo path: {shutil.which('cargo', path=env['PATH'])}")

    print(" ".join(colcon_command))

    build_proc = subprocess.Popen(
        colcon_command,
        env=env
    )

    rc = build_proc.wait()

    # Print rosidl type description arguments files so include_paths is visible in CI logs.
    for pkg in packages_to_build:
        args_json = build_base / pkg.name / "rosidl_generator_type_description__arguments.json"
        if args_json.exists():
            print(f"[DEBUG] {args_json}:")
            print(args_json.read_text())

    exit(rc)

if __name__ == "__main__":
    main()
