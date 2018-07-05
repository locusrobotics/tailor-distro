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
from rosdistro.source_repository_specification import SourceRepositorySpecification
from rosdistro.repository import Repository
from rosdistro.writer import yaml_from_distribution_file
from urllib.parse import urlsplit


# pin --distro ros1 REPOSITORY
# compare --distro ros1 REPOSITORY --raw
# import --distro ros2 [--upstream bouncy] REPOSITORY [--source --release]
# info --distro ros1 REPOSITORY
# query --origin {{ url_regex }} --pinned --unpinned


class BaseVerb(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def execute(self, index, distro):
        internal_index_path = index.resolve().as_uri()
        self.internal_index = get_index(internal_index_path)
        self.internal_distro = get_distribution(self.internal_index, distro)
        self.internal_distro_file = self.internal_index.distributions[distro]['distribution'][-1]

    def register_arguments(self, parser):
        parser.set_defaults(verb=self.execute)
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")
        parser.add_argument('--index', type=pathlib.Path, default='rosdistro/index.yaml', help="Index URL override")

    def repositories_arg(self, parser):
        parser.add_argument('repositories', nargs='+', metavar='REPO', help="Repositories to operate on")

    def upstream_arg(self, parser):
        parser.add_argument('--upstream-index', help="Upstream index URL override")
        parser.add_argument('--upstream-distro', help="Upstream distribution override")

    def load_upstream(self, distro, upstream_index, upstream_distro):
        recipes = yaml.safe_load(pathlib.Path('rosdistro/recipes.yaml').open())
        info = recipes['common']['distributions'][distro]['upstream']
        index = get_index(upstream_index if upstream_index is not None else info['url'])
        self.upstream_distro = get_distribution(
            index,
            upstream_distro if upstream_distro is not None else info['name']
        )

    def write_internal_distro(self):
        distro_file_path = pathlib.Path(self.internal_distro_file[len('file://'):])
        distro_file_path.write_text(yaml_from_distribution_file(self.internal_distro))


class ImportVerb(BaseVerb):
    """Import a source repository from one distribution to another."""
    name = 'import'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)
        self.upstream_arg(parser)

    def execute(self, repositories, index, distro, upstream_index, upstream_distro):
        super().execute(index, distro)
        self.load_upstream(distro, upstream_index, upstream_distro)

        for repo in repositories:
            try:
                source_repo_data = self.upstream_distro.repositories[repo].source_repository.get_data()
                status = self.upstream_distro.repositories[repo].source_repository.status
            except (KeyError, AttributeError):
                click.echo(click.style(f'Unable to find source entry for repo {repo} in upstream distro', fg='red'),
                           err=True)
                continue

            source_repo_data.pop('test_pull_requests', None)
            source_repo_data.pop('test_commits', None)

            click.echo(f"Writing source entry for repo {repo} ...")

            try:
                self.internal_distro.repositories[repo].source_repository = \
                    SourceRepositorySpecification(repo, source_repo_data)
            except KeyError:
                self.internal_distro.repositories[repo] = Repository(
                    name=repo, doc_data={}, release_data={}, status_data={'status': status},
                    source_data=source_repo_data)

        self.write_internal_distro()


class CompareVerb(BaseVerb):
    """Compare source repositories across two ROS distributions."""
    name = 'compare'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)
        self.upstream_arg(parser)
        parser.add_argument('--missing', action='store_true', help="Display repositories missing downstream")

    def execute(self, repositories, index, distro, upstream_index, upstream_distro, missing):
        super().execute(index, distro)
        self.load_upstream(distro, upstream_index, upstream_distro)

        if missing:
            missing_repos = self.upstream_distro.repositories.keys() - self.internal_distro.repositories.keys()
            repositories += missing_repos

        for repo in repositories:
            self.print_diff(repo)

    def print_diff(self, repo):
        if repo in self.internal_distro.repositories:
            click.echo(click.style(f'{repo}:'))
        else:
            click.echo(click.style(f'+{repo}:', fg='green'))

        for field in ['type', 'url', 'version']:
            try:
                upstream = self.upstream_distro.repositories[repo].source_repository.get_data().get(field, None)
            except (KeyError, AttributeError):
                upstream = None
            try:
                internal = self.internal_distro.repositories[repo].source_repository.get_data().get(field, None)
            except (KeyError, AttributeError):
                internal = None

            if internal != upstream:
                if internal is not None:
                    click.echo(click.style(f'    -{field}: {internal}', fg='red'))
                if upstream is not None:
                    click.echo(click.style(f'    +{field}: {upstream}', fg='green'))


class PinVerb(BaseVerb):
    """Pin a package version to the latest tag available on the source branch."""
    name = 'pin'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)

    def execute(self, repositories, index, distro):
        super().execute(index, distro)

        # TODO(pbovbel) Add interactive auth creation
        try:
            token_path = pathlib.Path('~/.git-tokens').expanduser()
            github_token = json.load(token_path.open()).get('github', None)
            github_client = github.Github(github_token)
        except Exception:
            click.echo('Unable to find your github token at {token_path}', err=True, color='red')
            raise

        for repo in repositories:
            data = self.internal_distro.repositories[repo]
            try:
                source_url = data.source_repository.url
                source_branch = data.source_repository.version
            except (KeyError, AttributeError):
                click.echo("No source entry for repo {repo}", err=True, color='yellow')
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

            if data.release_repository is None:
                data.release_repository = ReleaseRepositorySpecification(
                    repo_name, {'version': latest_tag, 'url': source_url, 'tags': {'release': '{{ version }}'}}
                )
            else:
                data.release_repository.version = latest_tag

            # TODO(pbovbel) set status description for who pinned when and how far behind

        self.write_internal_distro()

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

    for verb in [verb() for verb in BaseVerb.__subclasses__()]:
        verb.register_arguments(subparsers.add_parser(verb.name, help=verb.__doc__))

    args = vars(parser.parse_args())

    verb = args.pop('verb')

    if verb is not None:
        sys.exit(verb(**args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
