#!/usr/bin/python3
import argparse

import abc
import click
import github
import json
import pathlib
import sys
import yaml

from collections import deque
from rosdistro import get_index, get_distribution
from rosdistro.release_repository_specification import ReleaseRepositorySpecification
from rosdistro.writer import yaml_from_distribution_file
from urllib.parse import urlsplit


# pin --distro ros1 REPOSITORY
# compare --distro ros1 REPOSITORY --raw
# import --distro ros2 [--upstream bouncy] REPOSITORY [--source --release]
# info --distro ros1 REPOSITORY --raw
# query --origin {{ url_regex }} --pinned --unpinned


class BaseVerb(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def execute(self, **kwargs):
        pass

    def register_verb(self, parser):
        parser.set_defaults(verb=self.execute)

    def arg_distro(self, parser):
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")

    def arg_repositories(self, parser):
        parser.add_argument('repositories', nargs='+', metavar='REPO', help="Repositories to operate on")


class PinVerb(BaseVerb):
    """Pin a package version to the latest tag available on the source branch."""
    name = 'pin'

    def register_arguments(self, parser):
        self.register_verb(parser)
        self.arg_distro(parser)
        self.arg_repositories(parser)

    def execute(self, repositories, distro):
        internal_index_path = pathlib.Path('rosdistro/index.yaml').resolve()
        internal_index = get_index(internal_index_path.as_uri())
        internal_distro = get_distribution(internal_index, distro)

        # recipes = yaml.safe_load(pathlib.Path('rosdistro/recipes.yaml').open())
        # upstream_info = recipes['common']['distros'][distro]['upstream']
        # upstream_index = get_index(upstream_info['url'])
        # upstream_distro = get_distribution(upstream_index, upstream_info['name'])
        # print(upstream_distro)

        # TODO(pbovbel) Add interactive auth creation
        try:
            token_path = pathlib.Path('~/.git-tokens').expanduser()
            github_token = json.load(token_path.open()).get('github', None)
            github_client = github.Github(github_token)
        except Exception:
            click.echo('Unable to find your github token at {}'.format(token_path), err=True, color='red')
            raise

        for repo in repositories:
            try:
                source_url = internal_distro.repositories[repo].source_repository.url
                source_branch = internal_distro.repositories[repo].source_repository.version
            except (KeyError, AttributeError):
                click.echo("No source entry for repo {}".format(repo), err=True, color='yellow')
                return None

            # TODO(pbovbel) Abstract interface away for github/bitbucket/gitlab
            repo_name = urlsplit(source_url).path[len('/'):-len('.git')]
            gh_repo = github_client.get_repo(repo_name, lazy=False)
            gh_branch = gh_repo.get_branch(source_branch)

            # Find latest tag on source_branch
            head = gh_branch.commit
            queued = deque([(head, 0)])
            tags = {tag.commit.sha: tag.name for tag in gh_repo.get_tags()}

            # Breadth first search from branch head until we find a tagged commit
            while queued:
                commit, age = queued.popleft()
                try:
                    latest_tag = tags[commit.sha]
                    break
                except KeyError:
                    queued.extend(zip(commit.parents, [age + 1]*len(commit.parents)))

            try:
                click.echo(f'Found tag {latest_tag} for repo {repo} on branch {source_branch}, {age} commit(s) behind')
            except NameError:
                click.echo(f'Unable to find the latest tag for repo {repo} on branch {source_branch}', err=True,
                           color='yellow')
                continue

            if internal_distro.repositories[repo].release_repository is None:
                internal_distro.repositories[repo].release_repository = ReleaseRepositorySpecification(
                    repo_name, {'version': latest_tag, 'url': source_url, 'tags': {'release': '{{ version }}'}}
                )
            else:
                internal_distro.repositories[repo].release_repository.version = latest_tag

        distro_file = internal_index.distributions[distro]['distribution'][-1]
        distro_file_path = pathlib.Path(distro_file[len('file://'):])
        distro_file_path.write_text(yaml_from_distribution_file(internal_distro))


# class CompareVerb(BaseVerb):
#     """Compare a package entry to another distribution"""
#     name = 'compare'
#
#     def register_arguments(self, parser):
#         super(CompareVerb, self).register_arguments(parser)
#         parser.add_argument('--compare-arg-1', type=str, help="fdsa")
#
#     def execute(self, **kwargs):
#         print(kwargs)
#
#
# class QueryVerb(BaseVerb):
#     """Query package names"""
#     name = 'query'
#
#     def register_arguments(self, parser):
#         super(CompareVerb, self).register_arguments(parser)
#         parser.add_argument('query', type=str, help="fdsa")
#
#     def execute(self, **kwargs):
#         print(kwargs)


def main():
    parser = argparse.ArgumentParser(description="TODO")
    subparsers = parser.add_subparsers(dest='verb', help='Subcommand')

    for verb in [PinVerb()]:
        verb.register_arguments(subparsers.add_parser(verb.name, help=verb.__doc__))

    args = vars(parser.parse_args())

    verb = args.pop('verb')

    if verb is not None:
        sys.exit(verb(**args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
