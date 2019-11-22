#!/usr/bin/python3
import click

from .base import BaseVerb


class QueryVerb(BaseVerb):
    """Query a distribution for package names."""
    name = 'query'

    def register_arguments(self, parser):
        super().register_arguments(parser)
        self.filter_args(parser)
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--pinned', action='store_true')
        group.add_argument('--unpinned', action='store_true')

    def execute(self, rosdistro_repo, name_pattern, url_pattern, pinned, unpinned):
        super().execute(rosdistro_repo)
        repos = set()
        for repo in self.rosdistro_repo.get_repo_names(name_pattern, url_pattern):
            rel_repo = self.rosdistro_repo[repo].release_repository

            if pinned and (rel_repo is None or rel_repo.version is None):
                continue
            elif unpinned and rel_repo is not None and rel_repo.version is not None:
                continue

            repos.add(repo)

        click.echo(' '.join(sorted(repos)))
