import argparse
import pathlib
import json
import yaml
import os
import subprocess

from typing import List

from . import YamlLoadAction
from .blossom import Graph, GraphPackage, DebianGenerator


def load_json(path):
    repos = {}
    with open(path, "r") as f:
        for line in f.readlines():
            info = json.loads(line)
            repos[info['repo']] = info["sha"]
        return repos


def get_build_list(graph: Graph, recipe: dict | None = None):
    if recipe:
        root_packages = recipe["distributions"][graph.distribution]["root_packages"]
    else:
        root_packages = []

    packages, _ = graph.build_list(root_packages)

    return list(packages.keys())


def main():
    parser = argparse.ArgumentParser(description="Create package graph(s) based on a recipe")
    parser.add_argument("--recipe", action=YamlLoadAction, required=True)
    parser.add_argument("--ros1-graph", type=pathlib.Path, required=True)
    parser.add_argument("--ros2-graph", type=pathlib.Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ros1_graph = Graph.from_yaml(args.ros1_graph)

    build_list = get_build_list(ros1_graph, args.recipe)
    print(build_list)
    print(len(build_list))

    #ros2_graph = Graph.from_yaml(args.ros2_graph)

    #download_list = list(download_list.union(get_download_list(args.recipe, ros2_graph)))

    #with open("packages.txt", "w") as f:
    #    f.writelines(download_list)


if __name__ == '__main__':
    main()
