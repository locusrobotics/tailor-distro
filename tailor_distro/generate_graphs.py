import argparse
import pathlib
import json

from datetime import datetime, timezone

from . import YamlLoadAction
from .blossom import Graph


def load_repositories(path):
    repos = {}
    with open(path, "r") as f:
        for line in f.readlines():
            info = json.loads(line)
            repos[info['repo']] = info["sha"]
        return repos


def generate_graphs(recipe: dict, workspace: pathlib.Path, release_label: str, build_date: str):
    graphs = Graph.from_recipe(recipe, workspace, release_label, build_date)

    for graph in graphs:
        graph.write_yaml(workspace / pathlib.Path("graphs"))


def main():
    parser = argparse.ArgumentParser(description="Create package graph(s) based on a recipe")
    parser.add_argument("--recipe", action=YamlLoadAction, required=True)
    parser.add_argument("--release-label", required=True)
    parser.add_argument("--workspace", type=pathlib.Path, required=True)
    parser.add_argument("--timestamp", type=str, default=datetime.now(timezone.utc).strftime("%Y%m%d.%H%M%S"))
    #parser.add_argument("--ros1-repos", type=load_repositories, required=True)
    #parser.add_argument("--ros2-repos", type=load_repositories, required=True)
    args = parser.parse_args()

    #generate_graphs(args.recipe, args.workspace, args.ros1_repos, args.ros2_repos)
    generate_graphs(args.recipe, args.workspace, args.release_label, args.timestamp)


if __name__ == '__main__':
    main()
