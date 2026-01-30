import argparse
import pathlib
import json
import jinja2
import re

from datetime import datetime, timezone
from typing import List

from . import YamlLoadAction, SCHEME_S3
from .blossom import Graph


def load_repositories(path):
    repos = {}
    with open(path, "r") as f:
        for line in f.readlines():
            info = json.loads(line)
            repos[info['repo']] = info["sha"]
        return repos


def generate_graphs(recipe: dict, workspace: pathlib.Path, release_label: str, build_date: str, apt_configs: List[pathlib.Path]):
    graphs: List[Graph] = Graph.from_recipe(recipe, workspace, release_label, build_date)

    for graph in graphs:
        graph.write_yaml(workspace / pathlib.Path("graphs"))

    env = jinja2.Environment(
        loader=jinja2.PackageLoader("tailor_distro", "debian_templates"),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
    )
    env.filters['regex_replace'] = lambda s, find, replace: re.sub(find, replace, s)
    env.filters['union'] = lambda left, right: list(set().union(left, right))

    docker_dir = workspace / "debian"
    docker_dir.mkdir(exist_ok=True)

    for os_version in recipe["os"]["ubuntu"]:
        context = dict(
            os_name="ubuntu",
            os_version=os_version,
            release_label=release_label,
            bucket_name=recipe["common"]['apt_repo'][len(SCHEME_S3):],
            bucket_region=recipe["common"].get('apt_region', 'us-east-1'),
            **recipe["common"]
        )

        dockerfile = docker_dir / f"Dockerfile-{os_version}"

        control = env.get_template("Dockerfile.j2")
        stream = control.stream(**context)
        stream.dump(str(dockerfile))


def main():
    parser = argparse.ArgumentParser(description="Create package graph(s) based on a recipe")
    parser.add_argument("--recipe", action=YamlLoadAction, required=True)
    parser.add_argument("--release-label", required=True)
    parser.add_argument("--workspace", type=pathlib.Path, required=True)
    parser.add_argument("--timestamp", type=str, default=datetime.now(timezone.utc).strftime("%Y%m%d.%H%M%S"))
    parser.add_argument("--apt-configs", nargs="+", type=pathlib.Path, default=[])
    args = parser.parse_args()

    generate_graphs(args.recipe, args.workspace, args.release_label, args.timestamp, args.apt_configs)


if __name__ == '__main__':
    main()
