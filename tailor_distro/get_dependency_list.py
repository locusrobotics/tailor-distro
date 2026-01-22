import argparse
import pathlib
import json
import yaml
import os
import subprocess

from typing import List

from . import YamlLoadAction
from .blossom import Graph


def load_json(path):
    repos = {}
    with open(path, "r") as f:
        for line in f.readlines():
            info = json.loads(line)
            repos[info['repo']] = info["sha"]
        return repos


def get_download_list(recipe: dict, graph: Graph):
    root_packages = recipe["distributions"][graph.distribution]["root_packages"]
    _, downloads = graph.build_list(root_packages)

    print(downloads)

    download_list = set()

    for package in downloads.values():
        apt_name = package.debian_name(*graph.debian_info)
        version = package.apt_candidate_version

        download_list.add(f"{apt_name}={version}\n")

        for dep in package.apt_depends:
            download_list.add(f"{dep}\n")

    return download_list


def main():
    parser = argparse.ArgumentParser(description="Create package graph(s) based on a recipe")
    parser.add_argument("--recipe", action=YamlLoadAction, required=True)
    parser.add_argument("--ros1-graph", type=pathlib.Path, required=True)
    parser.add_argument("--ros2-graph", type=pathlib.Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ros1_graph = Graph.from_yaml(args.ros1_graph)

    download_list = get_download_list(args.recipe, ros1_graph)

    ros2_graph = Graph.from_yaml(args.ros2_graph)

    download_list = list(download_list.union(get_download_list(args.recipe, ros2_graph)))

    with open("packages.txt", "w") as f:
        f.writelines(download_list)


if __name__ == '__main__':
    main()
