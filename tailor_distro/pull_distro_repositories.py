#!/usr/bin/python3
import argparse
import click
import pathlib
import rosdistro
import sys
import github
import tarfile
import glob
import shutil

from catkin_pkg.package import parse_package
from concurrent.futures import ThreadPoolExecutor
from jinja2 import Environment, BaseLoader
from shutil import rmtree
from typing import Any, Mapping
from urllib.parse import urlsplit
from urllib import request

from . import YamlLoadAction


def pull_repository(repo_name, distro_data, repo_dir, github_client, upstream_name):
    click.echo(f'Processing {repo_name} ...', err=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    try:
        url = distro_data.release_repository.url
    except AttributeError:
        url = distro_data.source_repository.url

    try:
        version_template = distro_data.release_repository.tags['release']
        context = {
            'package': repo_name,
            'upstream': upstream_name,
            'version': distro_data.release_repository.version
        }
        version = Environment(loader=BaseLoader()).from_string(version_template).render(**context)
    except (AttributeError, KeyError):
        version = distro_data.source_repository.version

    try:
        package_names = distro_data.release_repository.package_names
        if package_names != [repo_name]:
            package_whitelist = package_names
    except AttributeError:
        package_whitelist = None

    # TODO(pbovbel) Abstract interface away for github/bitbucket/gitlab
    gh_repo_name = urlsplit(url).path[len('/'):-len('.git')]
    gh_repo = github_client.get_repo(gh_repo_name, lazy=False)
    archive_url = gh_repo.get_archive_link('tarball', version)

    archive_file = repo_dir / f'{repo_name}.tar.gz'
    with open(archive_file, 'wb') as tarball:
        tarball.write(request.urlopen(archive_url).read())
    with tarfile.open(archive_file) as tar:
        tar.extractall(path=repo_dir)

    # Remove all except whitelisted packages
    if package_whitelist:
        found_packages = glob.glob(str(repo_dir / '**/package.xml'), recursive=True)
        for package_xml_path in found_packages:
            package = parse_package(package_xml_path)
            if package.name not in package_whitelist:
                click.echo(f'Removing {package.name}, not in whitelist', err=True)
                shutil.rmtree(pathlib.Path(package_xml_path).parent.resolve())


def pull_distro_repositories(
        src_dir: pathlib.Path, recipes: Mapping[str, Any], clean: bool, github_key: str = None) -> None:
    """Pull all the packages in all ROS distributions to disk
    :param src_dir: Directory where sources should be pulled.
    :param recipes: Recipe configuration defining distributions.
    :param github_key: Github API key.
    """
    index = rosdistro.get_index(rosdistro.get_index_url())

    github_client = github.Github(github_key)

    common_options = recipes['common']

    with ThreadPoolExecutor() as executor:

        for distro_name, distro_options in common_options['distributions'].items():

            distro = rosdistro.get_distribution(index, distro_name)
            target_dir = src_dir / distro_name

            if clean and target_dir.exists():
                rmtree(str(target_dir))

            target_dir.mkdir(parents=True, exist_ok=not clean)

            for repo_name, distro_data in distro.repositories.items():
                repo_dir = target_dir / repo_name
                executor.submit(pull_repository, repo_name, distro_data, repo_dir, github_client,
                                upstream_name=distro_options['upstream']['name'])


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
