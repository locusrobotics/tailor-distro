import argparse
import pathlib
import yaml

from typing import Dict, Set

from .blossom import Graph, GraphPackage


def add_apt_depends(build_list: Dict[str, GraphPackage], downloads: Dict[str, GraphPackage]):
    download_list = set()

    for package in downloads.values():
        #apt_name = package.debian_name(*graph.debian_info)
        #version = package.apt_candidate_version

        #download_list.add(f"{apt_name}={version}\n")

        for dep in package.get_apt_depends():
            download_list.add(f"{dep}\n")

    # Also get any apt depends from the build list to satisfy the depends of the
    # package list we are about to build.
    for package in build_list.values():
        for dep in package.get_apt_depends():
            download_list.add(f"{dep}\n")

    return download_list

def get_download_list(graph: Graph):
    download_list: Set = set()

    for distro in ["ros1", "ros2"]:
        build_list, downloads = graph.build_list(distro, [])

        download_list = download_list.union(add_apt_depends(build_list, downloads))

    return list(download_list)


def main():
    parser = argparse.ArgumentParser(description="Get list of dependencies for all recipes")
    parser.add_argument("--graph", type=pathlib.Path, required=True)
    parser.add_argument("--recipe", type=pathlib.Path, required=True)
    parser.add_argument("--workspace", type=pathlib.Path, default=pathlib.Path("workspace"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)
    recipe = yaml.safe_load(args.recipe.read_text())

    all_deps = set()
    deps_path = pathlib.Path(f"{args.workspace}/dependencies")
    deps_path.mkdir(parents=True, exist_ok=True)

    for flavour, flavour_data in recipe["flavours"].items():
        apt_deps = set()
        for ros_dist, dist_data in flavour_data["distributions"].items():
            for pkg_name in dist_data["root_packages"]:
                deps = set(graph.all_apt_depends(pkg_name, ros_dist))
                apt_deps.update(deps)
                all_deps.update(deps)

        deps_file = deps_path / f"{flavour}_apt_dependencies.txt"

        print(f"Writing {deps_file}...")
        deps_file.write_text("\n".join(sorted(apt_deps)))


    deps_file = deps_path / "all_apt_dependencies.txt"
    print(f"Writing {deps_file}...")
    deps_file.write_text("\n".join(sorted(all_deps)))


if __name__ == '__main__':
    main()
