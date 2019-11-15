#!/usr/bin/python3
import click
import datetime
import github

from collections import deque
from rosdistro.release_repository_specification import ReleaseRepositorySpecification
from urllib.parse import urlsplit


from .base import BaseVerb, get_github_client


class PinVerb(BaseVerb):
    """Pin a package version to the latest tag available on the source branch."""
    name = 'pin'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)

    def execute(self, rosdistro_repo, repositories):
        super().execute(rosdistro_repo)

        github_client = get_github_client()

        actions = []

        for repo in repositories:
            click.echo(f'Pinning repo {repo} ...', err=True)
            data = self.rosdistro_repo[repo]

            try:
                if data.release_repository.url != data.source_repository.url:
                    click.echo(click.style("This package relies on a different release repository, needs to be bumped "
                                           "manually", fg='yellow'), err=True)
                    continue

            except (KeyError, AttributeError):
                pass

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
                        queued.extend(zip(commit.parents, [age + 1] * len(commit.parents)))
            except github.GithubException as e:
                click.echo(click.style(
                    f'Error processing branch {source_branch}: {e}', fg='red'), err=True)
                continue

            try:
                click.echo(f'Found tag {latest_tag} for on branch {source_branch}, {age} commit(s) behind')
            except NameError:
                click.echo(click.style(
                    f'Unable to find the latest tag on branch {source_branch}',
                    fg='yellow'), err=True)
                continue

            if data.release_repository is None:
                actions.append(f'{repo} ({latest_tag})')
                data.release_repository = ReleaseRepositorySpecification(
                    repo_name, {'version': latest_tag, 'url': source_url, 'tags': {'release': '{{ version }}'}}
                )
            else:
                actions.append(f'{repo} ({data.release_repository.version} -> {latest_tag})')
                data.release_repository.version = latest_tag

            # TODO(pbovbel) store name of pinner?
            data.status_description = f"Pinned {age} commits behind {source_branch} on {datetime.datetime.now()}"

        self.rosdistro_repo.write_internal_distro('Pinning {}'.format(', '.join(actions)))
