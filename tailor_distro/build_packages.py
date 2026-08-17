import argparse
import os
import pathlib
import pwd
import shutil
import subprocess
import sys

from typing import List, Tuple

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

    env = dict(args.recipe["common"]["distributions"][args.ros_distro]["env"])

    env["ROS_PACKAGE_PATH"] = ""
    env["CMAKE_PREFIX_PATH"] = ""
    env["PYTHONPATH"] = ""
    env["AMENT_PREFIX_PATH"] = ""
    env["LD_LIBRARY_PATH"] = ""
    env["PKG_CONFIG_PATH"] = ""
    env["MAKEFLAGS"] = "-j 2"

    current_workspace_prefix = install_path

    prepend_env_path(env, "LD_LIBRARY_PATH", str(current_optinstall_prefix / "lib"))
    prepend_env_path(env, "LD_LIBRARY_PATH", str(current_workspace_prefix / "lib"))
    prepend_env_path(env, "PYTHONPATH", str(current_optinstall_prefix / "lib/python3/dist-packages"))
    prepend_env_path(env, "PYTHONPATH", str(current_workspace_prefix / "lib/python3/dist-packages"))
    prepend_env_path(env, "PKG_CONFIG_PATH", str(current_optinstall_prefix / "lib/pkgconfig"))
    prepend_env_path(env, "PKG_CONFIG_PATH", str(current_workspace_prefix / "lib/pkgconfig"))
    prepend_env_path(env, "CMAKE_PREFIX_PATH", str(current_optinstall_prefix))
    prepend_env_path(env, "CMAKE_PREFIX_PATH", str(current_workspace_prefix))

    if args.ros_distro == "ros2":
        prepend_env_path(env, "AMENT_PREFIX_PATH", str(current_optinstall_prefix))
        prepend_env_path(env, "AMENT_PREFIX_PATH", str(current_workspace_prefix))
    if args.ros_distro == "ros1":
        prepend_env_path(env, "ROS_PACKAGE_PATH", str(current_optinstall_prefix / "share"))
        prepend_env_path(env, "ROS_PACKAGE_PATH", str(current_workspace_prefix / "share"))

    # Add source underlays. We may have both an installed distro (under /optinstall) and a
    # local workspace built prior.
    for underlay in args.recipe["common"]["distributions"][args.ros_distro].get("underlays", []):
        workspace_underlay_prefix = (
            args.workspace
            / pathlib.Path("install")
            / pathlib.Path(underlay)
            / pathlib.Path("install")
        )
        optinstall_prefix = optinstall_root / pathlib.Path(underlay)

        prepend_env_path(env, "LD_LIBRARY_PATH", str(workspace_underlay_prefix / "lib"))
        prepend_env_path(env, "LD_LIBRARY_PATH", str(optinstall_prefix / "lib"))
        prepend_env_path(env, "PYTHONPATH", str(workspace_underlay_prefix / "lib/python3/dist-packages"))
        prepend_env_path(env, "PYTHONPATH", str(optinstall_prefix / "lib/python3/dist-packages"))
        prepend_env_path(env, "PKG_CONFIG_PATH", str(workspace_underlay_prefix / "lib/pkgconfig"))
        prepend_env_path(env, "PKG_CONFIG_PATH", str(optinstall_prefix / "lib/pkgconfig"))
        prepend_env_path(env, "CMAKE_PREFIX_PATH", str(workspace_underlay_prefix))
        prepend_env_path(env, "CMAKE_PREFIX_PATH", str(optinstall_prefix))

        if underlay == "ros1":
            prepend_env_path(env, "ROS_PACKAGE_PATH", str(workspace_underlay_prefix / "share"))
            prepend_env_path(env, "ROS_PACKAGE_PATH", str(optinstall_prefix / "share"))
        if underlay == "ros2":
            prepend_env_path(env, "AMENT_PREFIX_PATH", str(workspace_underlay_prefix))
            prepend_env_path(env, "AMENT_PREFIX_PATH", str(optinstall_prefix))

    # Expose apt-installed packages so cmake can find them during builds of changed packages.
    system_opt = pathlib.Path(f"/opt/{graph.organization}/{graph.release_label}/{args.ros_distro}")

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

    # Applied after the recipe loop so it cannot be overwritten by recipe env values.
    if system_opt.exists():
        python_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        prepend_env_path(env, "LD_LIBRARY_PATH", str(system_opt / "lib"))
        prepend_env_path(env, "PYTHONPATH", str(system_opt / f"lib/python{python_ver}/dist-packages"))
        prepend_env_path(env, "PYTHONPATH", str(system_opt / f"lib/python{python_ver}/site-packages"))
        prepend_env_path(env, "PYTHONPATH", str(system_opt / "lib/python3/dist-packages"))
        prepend_env_path(env, "PKG_CONFIG_PATH", str(system_opt / "lib/pkgconfig"))
        prepend_env_path(env, "CMAKE_PREFIX_PATH", str(system_opt))
        if args.ros_distro == "ros1":
            prepend_env_path(env, "ROS_PACKAGE_PATH", str(system_opt / "share"))
        elif args.ros_distro == "ros2":
            prepend_env_path(env, "AMENT_PREFIX_PATH", str(system_opt))

    # ros2 packages (e.g. ros1_message_mirror) need ros1 Python modules at build time.
    if args.ros_distro == "ros2":
        ros1_system_opt = pathlib.Path(f"/opt/{graph.organization}/{graph.release_label}/ros1")
        if ros1_system_opt.exists():
            python_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            prepend_env_path(env, "PYTHONPATH", str(ros1_system_opt / f"lib/python{python_ver}/dist-packages"))
            prepend_env_path(env, "PYTHONPATH", str(ros1_system_opt / "lib/python3/dist-packages"))
            prepend_env_path(env, "ROS_PACKAGE_PATH", str(ros1_system_opt / "share"))
            prepend_env_path(env, "CMAKE_PREFIX_PATH", str(ros1_system_opt))

    print("Pre-build Environment:")
    for key, value in env.items():
        print(f"{key}={value}")

    print(sys.executable)

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

    # Build a clean environment with no host variable leakage.
    # PATH is derived from sys.executable so the venv's own bin dir (ninja,
    # ccache, empy, etc.) is reachable without inheriting anything from the
    # caller's shell.
    venv_bin = str(pathlib.Path(sys.executable).parent)
    rustup_home = os.environ.get("RUSTUP_HOME", "/opt/rust/rustup")
    cargo_home = os.environ.get("CARGO_HOME", "/opt/rust/cargo")
    cargo_bin = str(pathlib.Path(cargo_home) / pathlib.Path("bin"))
    # Derive HOME from the password database so git can find its global config
    # (e.g. the url.insteadOf rewrite) without reading os.environ.
    real_home = pwd.getpwuid(os.getuid()).pw_dir
    clean_env = {
        "PATH": f"{venv_bin}:{cargo_bin}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": real_home,
        "PYTHONNOUSERSITE": "1",
        "RUSTUP_HOME": rustup_home,
        "CARGO_HOME": cargo_home,
        "RUSTUP_INIT_SKIP_PATH_CHECK": "yes",
    }
    clean_env.update({k: str(v) for k, v in env.items()})

    # Print the resolved Cargo path from the build environment for debugging
    # toolchain mismatches in CI containers.
    print(f"Resolved cargo path: {shutil.which('cargo', path=clean_env['PATH'])}")

    print(" ".join(colcon_command))

    build_proc = subprocess.Popen(
        colcon_command,
        env=clean_env
    )

    exit(build_proc.wait())

if __name__ == "__main__":
    main()
