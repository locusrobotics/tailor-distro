#!/usr/bin/python3
import click

from .base import BaseVerb
from . import get_github_client


class ReleaseVerb(BaseVerb):
    """Pin a package version to the latest tag available on the source branch."""
    name = 'pin'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.repositories_arg(parser)

    def execute(self, repositories, rosdistro_path, distro):
        super().execute(rosdistro_path, distro)

        github_client = get_github_client()

        for repo in repositories:
            click.echo(f'Releasing repo {repo} ...', err=True)
            # data = self.internal_distro.repositories[repo]

            # try:
            #     if data.release_repository.url != data.source_repository.url:
            #         click.echo(click.style("This package relies on a different release repository, needs to be bumped "
            #                                "manually", fg='yellow'), err=True)
            #         continue

            # except (KeyError, AttributeError):
            #     pass

            # try:
            #     source_url = data.source_repository.url
            #     source_branch = data.source_repository.version
            # except (KeyError, AttributeError):
            #     click.echo(click.style("No source entry found", fg='yellow'), err=True)
            #     continue
