#!/usr/bin/python3
import argparse
import pathlib
import rosdistro
import subprocess
import sys
import yaml

from shutil import rmtree
from typing import Any, Mapping

from . import YamlLoadAction


def pull_distro_repositories(src_dir: pathlib.Path, recipes: Mapping[str, Any], github_key: str = None) -> None:
    """Pull all the packages in all ROS distributions to disk
    :param src_dir: Directory where sources should be pulled.
    :param recipes: Recipe configuration defining distributions.
    :param github_key: Github API key.
    """
    index = rosdistro.get_index(rosdistro.get_index_url())

    for distro_name in recipes['common']['rosdistros']:

        distro = rosdistro.get_distribution(index, distro_name)
        target_dir = src_dir / distro_name

        repositories = {}
        for repo in distro.repositories.items():
            repositories[repo[0]] = {
                'type': repo[1].source_repository.type,
                'url': repo[1].source_repository.url,  # TODO(pbovbel) insert github key into URL
                'version': repo[1].source_repository.version
            }

        if target_dir.exists():
            rmtree(str(target_dir))

        target_dir.mkdir(parents=True, exist_ok=True)

        repositories_file = src_dir / (distro_name + '.repos')
        repositories_file.write_text(yaml.dump({'repositories': repositories}))

        subprocess.run([
            "vcs", "import", str(target_dir),
            "--input", str(repositories_file),
            "--retry", str(3),
            "--recursive",
            "--shallow",
        ], check=True)


def main():
    parser = argparse.ArgumentParser(description=pull_distro_repositories.__doc__)
    parser.add_argument('--src-dir', type=pathlib.Path, required=True)
    parser.add_argument('--recipes', action=YamlLoadAction, required=True)
    parser.add_argument('--github-key', type=str)
    args = parser.parse_args()

    sys.exit(pull_distro_repositories(**vars(args)))


if __name__ == '__main__':
    main()
