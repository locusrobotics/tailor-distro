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
import time

from catkin_pkg.package import parse_package
from concurrent.futures import ThreadPoolExecutor
from jinja2 import Environment, BaseLoader
from shutil import rmtree
from typing import Any, List, Mapping, Optional
from urllib.parse import urlsplit
from urllib import request

from . import YamlLoadAction


def pull_repository(repo_name: str, url: str, version: str, package_whitelist: Optional[List[str]],
                    repo_dir: pathlib.Path, github_client: github.Github) -> None:
    """ Download and unpack a repository from github
    :param repo_name: Name of repository.
    :param url: Url of github repository.
    :param version: Ref in repository to pull.
    :param package_whitelist: Optional package whitelist, remove all others.
    :param repo_dir: Directory where to unpack repostiory.
    :param github_client: Github client.
    """
    click.echo(f'Pulling repository {repo_name} ...', err=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    retry = 3
    while True:
        try:
            # TODO(pbovbel) Abstract interface away for github/bitbucket/gitlab
            gh_repo_name = urlsplit(url).path[len('/'):-len('.git')]
            gh_repo = github_client.get_repo(gh_repo_name, lazy=False)
            archive_url = gh_repo.get_archive_link('tarball', version)
            archive_file = repo_dir / f'{repo_name}.tar.gz'
            with open(archive_file, 'wb') as tarball:
                tarball.write(request.urlopen(archive_url).read())

            with tarfile.open(archive_file) as tar:
                tar.extractall(path=repo_dir)
            break
        except github.GithubException as e:
            click.echo(click.style(f"Failed to determine archive URL for {repo_name} from {url}: {e}",
                                   fg="yellow"), err=True)
            if retry <= 0:
                raise

        except Exception as e:
            print(type(e))
            click.echo(click.style(f"Failed extract archive {archive_url} to {repo_dir}: {e}",
                                   fg="yellow"), err=True)
            if retry <= 0:
                raise

        print(retry)
        time.sleep(5)
        retry -= 1

    # Remove all except whitelisted packages
    if package_whitelist:
        try:
            found_packages = glob.glob(str(repo_dir / '**/package.xml'), recursive=True)
            for package_xml_path in found_packages:
                package = parse_package(package_xml_path)
                if package.name not in package_whitelist:
                    click.echo(f'Removing {package.name}, not in {repo_name} whitelist', err=True)
                    shutil.rmtree(pathlib.Path(package_xml_path).parent.resolve())
        except Exception as e:
            click.echo(click.style(f"Unable to reduce {repo_dir} to whitelist {package_whitelist}: {e}",
                                   fg="yellow"), err=True)
            raise


def pull_distro_repositories(src_dir: pathlib.Path, recipes: Mapping[str, Any], rosdistro_index: pathlib.Path,
                             github_key: str, clean: bool) -> int:
    """Pull all the packages in all ROS distributions to disk
    :param src_dir: Directory where sources should be pulled.
    :param recipes: Recipe configuration defining distributions.
    :param rosdistro_index: Path to rosdistro index.
    :param github_key: Github API key.
    :param clean: Whether to delete distro folders before pulling.
    :returns: Result code
    """
    index = rosdistro.get_index(rosdistro_index.resolve().as_uri())

    github_client = github.Github(github_key)

    common_options = recipes['common']

    results = {}

    with ThreadPoolExecutor() as executor:

        for distro_name, distro_options in common_options['distributions'].items():

            distro = rosdistro.get_distribution(index, distro_name)
            target_dir = src_dir / distro_name

            if clean and target_dir.exists():
                click.echo(f"Deleting {target_dir} ...", err=True)
                rmtree(str(target_dir))

            target_dir.mkdir(parents=True, exist_ok=not clean)

            for repo_name, distro_data in distro.repositories.items():
                # release.url overrides source.url. In most cases they should be equivalent, but sometimes we want to
                # pull from a bloomed repository with patches
                try:
                    url = distro_data.release_repository.url
                except AttributeError:
                    url = distro_data.source_repository.url

                # We're fitting to the rosdistro standard here, release.tags.release is a template that can take
                # parameters, though in our case it's usually just '{{ version }}'.
                try:
                    version_template = distro_data.release_repository.tags['release']
                    context = {
                        'package': repo_name,
                        'upstream': distro_options['upstream']['name'],
                        'version': distro_data.release_repository.version
                    }
                    version = Environment(loader=BaseLoader()).from_string(version_template).render(**context)
                except (AttributeError, KeyError):
                    version = distro_data.source_repository.version

                # Repurpose the rosdistro 'release.packages' field as an optional whitelist to prevent building
                # packages we don't want.
                if distro_data.release_repository and distro_data.release_repository.package_names != [repo_name]:
                    package_whitelist = distro_data.release_repository.package_names
                else:
                    package_whitelist = None

                repo_dir = target_dir / repo_name

                # TODO(pbovbel) convert to async/await
                results[repo_name] = executor.submit(
                    pull_repository, repo_name, url, version, package_whitelist, repo_dir, github_client)

    # TODO(pbovbel) Handle errors and retry? We're definitely hitting rate limits sometimes
    exceptions = {name: result.exception() for name, result in results.items()
                  if result.exception() is not None}

    if exceptions:
        for repo_name, exception in exceptions.items():
            click.echo(click.style(f"Unable to pull {repo_name}: {exception}", fg="red"), err=True)
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description=pull_distro_repositories.__doc__)
    parser.add_argument('--src-dir', type=pathlib.Path, required=True)
    parser.add_argument('--recipes', action=YamlLoadAction, required=True)
    parser.add_argument('--rosdistro-index', type=pathlib.Path, required=True)
    parser.add_argument('--github-key', type=str)
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args()

    sys.exit(pull_distro_repositories(**vars(args)))


if __name__ == '__main__':
    main()
