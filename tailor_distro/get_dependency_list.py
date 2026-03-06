import argparse
import pathlib

from .blossom import Graph


def get_download_list(graph: Graph, recipe: dict | None = None):
    if recipe:
        root_packages = recipe["distributions"][graph.distribution].get("root_packages", None)

        if root_packages is None:
            return set()
    else:
        root_packages = []

    build_list, downloads = graph.build_list(root_packages)

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


def main():
    parser = argparse.ArgumentParser(description="Get list of dependencies for a graph")
    parser.add_argument("--recipe", type=pathlib.Path)
    parser.add_argument("--ros1-graph", type=pathlib.Path, required=True)
    parser.add_argument("--ros2-graph", type=pathlib.Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ros1_graph = Graph.from_yaml(args.ros1_graph)

    download_list = get_download_list(ros1_graph, args.recipe)

    ros2_graph = Graph.from_yaml(args.ros2_graph)

    download_list = list(download_list.union(get_download_list(ros2_graph, args.recipe)))

    with open("packages.txt", "w") as f:
        f.writelines(download_list)


if __name__ == '__main__':
    main()
