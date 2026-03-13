import argparse
import pathlib
import subprocess
import jinja2
import re
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

def generate_build_script(distribution: str, **kwargs) -> str:
    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    build_script = f"build-{distribution}.sh"

    control = env.get_template("build.j2")
    stream = control.stream(**kwargs)
    stream.dump(str(build_script))

    os.chmod(build_script, mode=0o0755)

    return build_script

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

    print(unknown_args)

    graph = Graph.from_yaml(args.graph)

    build_list, ignore = get_build_list(graph, args.ros_distro)

    build_packages = [pkg.name for pkg in build_list]

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

    # Source underlays. We may have both an installed distro (under /opt) and a
    # local workspace built prior.
    underlays = []

    env = args.recipe["common"]["distributions"][args.ros_distro]["env"]

    env["ROS_PACKAGE_PATH"] = ""
    env["CMAKE_PREFIX_PATH"] = ""
    env["PYTHONPATH"] = ""

    for underlay in args.recipe["common"]["distributions"][args.ros_distro].get("underlays", []):
        optinstall_prefix = pathlib.Path(
            f"optinstall/{graph.organization}/{graph.release_label}/{underlay}"
        ).absolute()
        env["LD_LIBRARY_PATH"] = str(optinstall_prefix / "lib")
        env["PYTHONPATH"] = str(optinstall_prefix / "lib/python3/dist-packages")
        env["ROS_PACKAGE_PATH"] = str(optinstall_prefix / "share")
        env["PKG_CONFIG_PATH"] = str(optinstall_prefix / "lib/pkgconfig")
        env["CMAKE_PREFIX_PATH"] = str(optinstall_prefix)

    cxx_flags = args.recipe["common"]["cxx_flags"]
    cxx_standard = args.recipe["common"]["cxx_standard"]
    python_version = args.recipe["common"]["python_version"]

    for key, value in args.recipe["common"]["distributions"][args.ros_distro]["env"].items():
        env[key] = value

    env["ROS_DISTRO_OVERRIDE"] = f"{graph.organization}-{graph.release_label}"

    print("Pre-build Environment:")
    for key, value in env.items():
        print(f"{key}={value}")

    script = generate_build_script(
        args.ros_distro,
        underlays=underlays,
        build_base=build_base,
        packages=build_packages,
        base_paths=base_path,
        install_base=install_path,
        cxx_flags=cxx_flags,
        cxx_standard=cxx_standard,
        python_version=python_version,
        env=env,
        clean=(not args.no_clean),
        unknown_args=unknown_args,
        graph=str(args.graph),
        ros_version=args.ros_distro
    )

    build_proc = subprocess.Popen(
        ["bash", script],
    )

    exit(build_proc.wait())

if __name__ == "__main__":
    main()
