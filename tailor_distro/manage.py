#!/usr/bin/python3
import argparse

import abc
import click
import datetime
import github
import json
import pathlib
import re
import sys
import yaml

from collections import deque, defaultdict
from rosdistro import get_index, get_distribution
from rosdistro.release_repository_specification import ReleaseRepositorySpecification
from rosdistro.source_repository_specification import SourceRepositorySpecification
from rosdistro.repository import Repository
from rosdistro.writer import yaml_from_distribution_file
from urllib.parse import urlsplit


class BaseVerb(metaclass=abc.ABCMeta):
    """Abstract base class for all distro management verbs."""

    @abc.abstractmethod
    def execute(self, index, distro):
        internal_index_path = index.resolve().as_uri()
        self.internal_index = get_index(internal_index_path)
        self.internal_distro = get_distribution(self.internal_index, distro)
        self.internal_distro_file = self.internal_index.distributions[distro]['distribution'][-1]

    def register_arguments(self, parser):
        parser.set_defaults(verb=self.execute)
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")
        # TODO(pbovbel) Use path relative to package?
        parser.add_argument('--index', type=pathlib.Path, default='rosdistro/index.yaml', help="Index URL override")

    def repositories_arg(self, parser):
        parser.add_argument('repositories', nargs='*', metavar='REPO', help="Repositories to operate on")

    def upstream_arg(self, parser):
        parser.add_argument('--upstream-distro', help="Upstream distribution override")
        parser.add_argument('--upstream-index', help="Upstream index URL override")

    def load_upstream(self, distro, upstream_index, upstream_distro):
        recipes = yaml.safe_load(pathlib.Path('rosdistro/recipes.yaml').open())
        try:
            info = recipes['common']['distributions'][distro]['upstream']
        except KeyError:
            info = None
        index = get_index(upstream_index if upstream_index is not None else info['url'])
        self.upstream_distro = get_distribution(
            index,
            upstream_distro if upstream_distro is not None else info['name']
        )

    def write_internal_distro(self):
        distro_file_path = pathlib.Path(self.internal_distro_file[len('file://'):])
        distro_file_path.write_text(yaml_from_distribution_file(self.internal_distro))


class QueryVerb(BaseVerb):
    """Query a distribution for package names."""
    name = 'query'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        parser.add_argument('--name-pattern', type=re.compile, help="Pattern to match in repository name")
        parser.add_argument('--url-pattern', type=re.compile, help="Pattern to match in repository URL")
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--pinned', action='store_true')
        group.add_argument('--unpinned', action='store_true')

    def execute(self, distro, index, name_pattern, url_pattern, pinned, unpinned):
        super().execute(index, distro)
        repos = set(self.internal_distro.repositories.keys())
        if name_pattern is not None:
            repos &= {
                repo for repo, data in self.internal_distro.repositories.items()
                if name_pattern.match(repo)
            }
        if url_pattern is not None:
            repos &= {
                repo for repo, data in self.internal_distro.repositories.items()
                if data.source_repository is not None and url_pattern.match(data.source_repository.url)
            }

        if pinned:
            repos &= {
                repo for repo, data in self.internal_distro.repositories.items()
                if data.release_repository is not None
            }
        elif unpinned:
            repos &= {
                repo for repo, data in self.internal_distro.repositories.items()
                if data.release_repository is None
            }

        click.echo(' '.join(repos))


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
                click.echo(click.style(f'Unable to find source entry for repo {repo} in upstream distro', fg='yellow'),
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
    # TODO(pbovbel) add comparison for pinned version in release repository
    name = 'compare'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)
        self.upstream_arg(parser)
        parser.add_argument('--missing', action='store_true', help="Display repositories missing downstream")
        parser.add_argument('--raw', action='store_true', help="Output only package names")

    def execute(self, repositories, index, distro, upstream_index, upstream_distro, missing, raw):
        super().execute(index, distro)
        self.load_upstream(distro, upstream_index, upstream_distro)

        if missing:
            missing_repos = self.upstream_distro.repositories.keys() - self.internal_distro.repositories.keys()
            repositories += missing_repos

        diffs = {repo: self.get_diff(repo) for repo in repositories}

        for repo, diff in diffs.items():
            name = diff.pop('name', None)
            if diff:
                if 'unchanged' in name.keys():
                    click.echo(click.style(f'name: {repo}'))
                else:
                    click.echo(click.style(f'+name: {repo}', fg='green'))
                for field, values in diff.items():
                    for delta, value in values.items():
                        if delta == 'internal':
                            click.echo(click.style(f'    -{field}: {value}', fg='red'))
                        elif delta == 'upstream':
                            click.echo(click.style(f'    +{field}: {value}', fg='green'))

    def get_diff(self, repo):
        diff = defaultdict(dict)
        if repo not in self.upstream_distro.repositories:
            return diff
        elif repo not in self.internal_distro.repositories:
            diff['name'] = {'upstream': repo}
        else:
            diff['name'] = {'unchanged': repo}

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
                    diff[field]['internal'] = internal
                if upstream is not None:
                    diff[field]['upstream'] = upstream
        return diff


class PinVerb(BaseVerb):
    """Pin a package version to the latest tag available on the source branch."""
    name = 'pin'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)

    def execute(self, repositories, index, distro):
        super().execute(index, distro)

        # TODO(pbovbel) Add interactive auth creation?
        try:
            token_path = pathlib.Path('~/.git-tokens').expanduser()
            github_token = json.load(token_path.open()).get('github', None)
            github_client = github.Github(github_token)
        except Exception:
            click.echo(click.style(f'Unable to find your github token at {token_path}', fg='red'), err=True)
            raise

        for repo in repositories:
            click.echo(f'Pinning repo {repo} ...', err=True)
            data = self.internal_distro.repositories[repo]
            try:
                source_url = data.source_repository.url
                source_branch = data.source_repository.version
            except (KeyError, AttributeError):
                click.echo(click.style("No source entry found", fg='yellow'), err=True)
                continue

            # TODO(pbovbel) Abstract interface away for github/bitbucket/gitlab
            try:
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
            except github.GithubException as e:
                click.echo(click.style(
                    f'Error processing branch {source_branch}: {e}', fg='red'), err=True)
                continue

            try:
                click.echo(f'Found tag {latest_tag} for on branch {source_branch}, {age} commit(s) behind')
            except NameError:
                click.echo(click.style(
                    f'Unable to find the latest tag on branch {source_branch}',
                    color='yellow'), err=True)
                continue

            if data.release_repository is None:
                data.release_repository = ReleaseRepositorySpecification(
                    repo_name, {'version': latest_tag, 'url': source_url, 'tags': {'release': '{{ version }}'}}
                )
            else:
                data.release_repository.version = latest_tag

            # TODO(pbovbel) store name of pinner?
            data.status_description = f"Pinned {age} commits behind {source_branch} on {datetime.datetime.now()}"

        self.write_internal_distro()


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
