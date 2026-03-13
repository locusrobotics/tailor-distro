import argparse
import pathlib

from typing import Dict, Set

from .blossom import Graph, GraphPackage


def add_apt_depends(build_list: Dict[str, GraphPackage], downloads: Dict[str, GraphPackage]):
    download_list = set()

    for package in downloads.values():
        #apt_name = package.debian_name(*graph.debian_info)
        #version = package.apt_candidate_version

        #download_list.add(f"{apt_name}={version}\n")

        for dep in package.apt_depends:
            download_list.add(f"{dep}\n")

    # Also get any apt depends from the build list to satisfy the depends of the
    # package list we are about to build.
    for package in build_list.values():
        for dep in package.apt_depends:
            download_list.add(f"{dep}\n")

    return download_list

def get_download_list(graph: Graph):
    download_list: Set = set()

    for distro in ["ros1", "ros2"]:
        build_list, downloads = graph.build_list(distro, [])

        download_list = download_list.union(add_apt_depends(build_list, downloads))

    return list(download_list)


def main():
    parser = argparse.ArgumentParser(description="Get list of dependencies for a graph")
    parser.add_argument("--graph", type=pathlib.Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)

    download_list = get_download_list(graph)

    with open("packages.txt", "w") as f:
        f.writelines(download_list)


if __name__ == '__main__':
    main()
