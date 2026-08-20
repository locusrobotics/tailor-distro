import argparse
import os
import pathlib
import pwd
import shutil
import subprocess
import sys

from typing import List, Tuple, Dict

from . import YamlLoadAction
from .blossom import Graph, GraphPackage


def get_build_list(graph: Graph, ros_distro: str, recipe: dict | None = None, rebuild_all: bool = False) -> Tuple[List[GraphPackage], List[GraphPackage]]:
    if recipe:
        root_packages = recipe["distributions"][ros_distro]["root_packages"]
    else:
        root_packages = []

    packages, ignore = graph.build_list(ros_distro, root_packages, rebuild_all=rebuild_all)

    return list(packages.values()), list(ignore.values())


def source_setups(files: List[pathlib.Path]) -> Dict[str, str]:
    env_vars = {}

    for file in files:
        if not file.exists():
            raise FileNotFoundError(f"Source setup file not found: {file}")

    sources = [f"source {file}" for file in files]

    # Source each setup file with a clean env, then dump out the env at the end
    # to parse
    command = f"env -i bash -c '{' && '.join(sources)} && env'"
    try:
        # Run command and capture output
        output = subprocess.check_output(command, shell=True, text=True)

        # Parse the 'key=value' lines into Python's environment
        for line in output.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key] = value

    except subprocess.CalledProcessError as e:
        print(f"Error sourcing files: {e}")

    print(f"Sourced environments: {' '.join(str(file) for file in files)}")

    return env_vars

def create_optinstall_dirs(root_dir: pathlib.Path, organization: str, release_label: str, ros_version: str, underlays: List[pathlib.Path]):
    print(f"creating optinstall dir with underlays: {' '.join(str(underlay) for underlay in underlays)}")
    # Create the root dir:
    ros_root = root_dir / organization / release_label / ros_version

    ros_root.mkdir(parents=True)

    if underlays:
        env = source_setups(underlays)
    else:
        env = {}

    print("Pre optinstall env")
    for key, value in env.items():
        print(f"{key}={value}")

    # Re-create the root colcon workspace for each distribution. The reason this is
    # needed is because we're building in an isolated environment. But then during
    # packaging we actually "merge" everything back together. This results in a final
    # installable set of debians that appears like they were build with --merge-install.
    # The only way to do this is to re-generate the setup scripts with --merge-install
    # so everything sources correctly.
    colcon = subprocess.Popen(
        [
            "colcon",
            "build",
            "--install-base", ros_root,
            "--base-paths", ros_root,
            "--merge-install",
        ],
        env=env
    )

    colcon.wait()


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

    # Packages whose SHA matches apt are not being rebuilt; ignore them to suppress
    # the "packages in workspace but haven't been built" warning.
    _, apt_packages = get_build_list(graph, args.ros_distro, rebuild_all=args.rebuild_all)
    apt_package_names = [pkg.name for pkg in apt_packages]

    # Install previously-built packages from the apt repo so they are available
    # as dependencies during the build without needing to rebuild them.
    apt_names = [
        f"{pkg.debian_name(graph.organization, graph.release_label)}={pkg.apt_candidate_version}"
        for pkg in apt_packages
        if pkg.apt_candidate_version
    ]
    if apt_names:
        print(f"[APT] Installing {len(apt_names)} unchanged packages...")
        subprocess.run(["sudo", "-E", "apt-get", "update", "-qq"], check=False)
        apt_result = subprocess.run(
            ["sudo", "-E", "apt-get", "install", "-y", "--no-install-recommends"] + apt_names,
            check=False
        )
        if apt_result.returncode != 0:
            print("[APT] apt-get install failed, packages may not be available as dependencies")

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

    env = dict(args.recipe["common"]["distributions"][args.ros_distro]["env"])

    # Sourcing setup files process/ordering:
    #
    # 1. Identify any underlays, both system (and prior built local optinstall)
    # 2. Source any distribution that may already exist (in part) under /opt/<organization>/....
    # 3. Source the local optinstall for this ROS distribution
    #    Passing the underlays into the local optinstall creation function ensures they are considered.
    # 4. And underlay may exist (e.g. when build ROS2 workspaces). That needs to be sourced as well.
    #
    # Note: The order of sourcing is important: system opt first, then local optinstall, then any underlay.

    # Determine system underlays first, but don't source yet
    underlays = []
    source_files = []

    underlay_keys = args.recipe["common"]["distributions"][args.ros_distro].get("underlays", [])

    # (1) Identify system/local underlay
    for underlay in underlay_keys:
        # System underlay may or may not exist yet. A fresh release/build will not have it
        system_underlay = pathlib.Path("/opt") / graph.organization / graph.release_label / underlay / "setup.bash"
        if system_underlay.exists():
            underlays.append(system_underlay)

        # A local underlay also may not exist, if no packages were built prior for this underlay in this CI run
        local_underlay = pathlib.Path("optinstall") / graph.organization / graph.release_label / underlay / "setup.bash"
        if local_underlay.exists():
            underlays.append(local_underlay)

        # Workspace underlay: ros1 packages built earlier in this same CI run land here.
        # Needed so ros2 packages using rosidl_from_ros1_package can find them via ROS_PACKAGE_PATH.
        ws_underlay = args.workspace / "install" / underlay / "install" / "setup.bash"
        if ws_underlay.exists():
            underlays.append(ws_underlay)

    system_opt = pathlib.Path("/opt") / graph.organization / graph.release_label / args.ros_distro / "setup.bash"
    if system_opt.exists() and system_opt not in underlays:
        underlays.append(system_opt)

    # Create local optinstall directory structure for this ROS distribution
    local_opt = pathlib.Path("optinstall") / graph.organization / graph.release_label / args.ros_distro / "setup.bash"
    create_optinstall_dirs(pathlib.Path("optinstall"), graph.organization, graph.release_label, args.ros_distro, underlays)

    # Since we passed the underlays into the optinstall workspace creation the local optinstall setup
    # should include those paths
    source_files.append(local_opt)

    env.update(source_setups(source_files))

    for key,value in env.items():
        print(f"{key}={value}")

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

    print(f"Packages already built: {' '.join(apt_package_names)}")

    if apt_package_names:
        colcon_command.extend(["--packages-ignore"] + apt_package_names)

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
