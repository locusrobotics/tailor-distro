#!/usr/bin/python3
import argparse
import click
import pathlib
import rosdistro
import subprocess
import sys
import yaml

from jinja2 import Environment, BaseLoader
from shutil import rmtree
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from . import YamlLoadAction


def process_url(url: str, organization: str, github_key: str = None) -> str:
    """Process URL to prepend an authentication key."""
    pieces = urlsplit(url)
    if github_key is not None and pieces.netloc == 'github.com' and pieces.path.startswith('/' + organization):
        pieces = pieces._replace(netloc=github_key + '@' + pieces.netloc)

    return urlunsplit(pieces)


def pull_distro_repositories(
        src_dir: pathlib.Path, recipes: Mapping[str, Any], clean: bool, github_key: str = None) -> None:
    """Pull all the packages in all ROS distributions to disk
    :param src_dir: Directory where sources should be pulled.
    :param recipes: Recipe configuration defining distributions.
    :param github_key: Github API key.
    """
    index = rosdistro.get_index(rosdistro.get_index_url())

    common_options = recipes['common']
    organization = common_options['organization']

    for distro_name in common_options['distributions'].keys():

        click.echo(f"Pulling distribution {distro_name} ...", err=True)

        distro = rosdistro.get_distribution(index, distro_name)
        target_dir = src_dir / distro_name

        repositories = {}
        for repo, data in distro.repositories.items():

            context = {
                'package': repo,
                'upstream': common_options['distributions'][distro_name]['upstream']['name'],
            }

            if data.release_repository:
                url = data.release_repository.url
                version = data.release_repository.tags['release']
                type = data.release_repository.type
                context['version'] = data.release_repository.version

                # TODO(pbovbel) implement package whitelist/blacklist via release_repository.packages
            elif data.source_repository:
                url = data.source_repository.url
                version = data.source_repository.version
                type = data.source_repository.type
            else:
                click.echo(click.style(f"No source or release entry for {repo}", fg='yellow'), err=True)
                continue

            repositories[repo] = {
                'type': type,
                'url': process_url(url, organization, github_key),
                'version': Environment(loader=BaseLoader()).from_string(version).render(**context)
            }

        if clean and target_dir.exists():
            rmtree(str(target_dir))

        target_dir.mkdir(parents=True, exist_ok=not clean)

        repositories_file = src_dir / (distro_name + '.repos')
        repositories_file.write_text(yaml.dump({'repositories': repositories}))

        vcs_command = [
            "vcs", "import", str(target_dir),
            "--input", str(repositories_file),
            "--retry", str(3),
            # "--recursive",
            "--shallow",
        ]
        click.echo(' '.join(vcs_command), err=True)
        subprocess.run(vcs_command, check=True)


def main():
    parser = argparse.ArgumentParser(description=pull_distro_repositories.__doc__)
    parser.add_argument('--src-dir', type=pathlib.Path, required=True)
    parser.add_argument('--recipes', action=YamlLoadAction, required=True)
    parser.add_argument('--github-key', type=str)
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args()

    sys.exit(pull_distro_repositories(**vars(args)))


if __name__ == '__main__':
    main()
