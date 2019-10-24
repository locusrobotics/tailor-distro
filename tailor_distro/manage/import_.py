#!/usr/bin/python3
import click

from rosdistro.source_repository_specification import SourceRepositorySpecification
from rosdistro.repository import Repository

from .base import BaseVerb


class ImportVerb(BaseVerb):
    """Import a source repository from one distribution to another."""
    name = 'import'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)
        self.upstream_arg(parser)

    def execute(self, rosdistro_repo, repositories, upstream_index, upstream_distro):
        super().execute(rosdistro_repo)
        upstream = self.rosdistro_repo.get_upstream_distro(upstream_index, upstream_distro)

        for repo in repositories:
            try:
                source_repo_data = upstream.repositories[repo].source_repository.get_data()
                status = upstream.repositories[repo].source_repository.status
            except (KeyError, AttributeError):
                click.echo(click.style(f'Unable to find source entry for repo {repo} in upstream distro', fg='yellow'),
                           err=True)
                continue

            source_repo_data.pop('test_pull_requests', None)
            source_repo_data.pop('test_commits', None)

            click.echo(f"Writing source entry for repo {repo} ...")

            repo_entry = self.rosdistro_repo[repo]
            if repo_entry:
                repo_entry.source_repository = SourceRepositorySpecification(repo, source_repo_data)
            else:
                self.rosdistro_repo.set_repo(repo, Repository(
                    name=repo, doc_data={}, release_data={}, status_data={'status': status},
                    source_data=source_repo_data))

        self.rosdistro_repo.write_internal_distro('Importing {} from {}'.format('/'.join(repositories), upstream_index))
