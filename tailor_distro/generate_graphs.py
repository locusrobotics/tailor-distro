import argparse
import pathlib
import json
import yaml
import os

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


def generate_graphs(recipe: dict, workspace: pathlib.Path, ros1_repos: dict, ros2_repos):
    graphs = Graph.from_recipe(recipe, workspace, ros1_repos, ros2_repos)

    for graph in graphs:
        graph.write_yaml(workspace / pathlib.Path("graphs"))


def main():
    parser = argparse.ArgumentParser(description="Create package graph(s) based on a recipe")
    parser.add_argument("--recipe", action=YamlLoadAction, required=True)
    parser.add_argument("--workspace", type=pathlib.Path, required=True)
    parser.add_argument("--ros1-repos", type=load_json, required=True)
    parser.add_argument("--ros2-repos", type=load_json, required=True)
    args = parser.parse_args()

    generate_graphs(args.recipe, args.workspace, args.ros1_repos, args.ros2_repos)


if __name__ == '__main__':
    main()
