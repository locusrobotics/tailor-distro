#!/usr/bin/python3
import click
import re

from .base import BaseVerb


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

    def execute(self, rosdistro_repo, name_pattern, url_pattern, pinned, unpinned):
        super().execute(rosdistro_repo)
        repos = self.rosdistro_repo.get_repo_names()
        if name_pattern is not None:
            repos = set([repo for repo in repos if name_pattern.match(repo)])
        if url_pattern is not None:
            repos = set([repo for repo in repos
                         if self.rosdistro_repo[repo].source_repository is not None and
                         url_pattern.match(self.rosdistro_repo[repo].source_repository.url)])

        if pinned:
            repos = set([repo for repo in repos
                         if self.rosdistro_repo[repo].release_repository and
                         self.rosdistro_repo[repo].release_repository.version is not None])
        elif unpinned:
            repos = set([repo for repo in repos
                         if self.rosdistro_repo[repo].release_repository is None or
                         self.rosdistro_repo[repo].release_repository.version is None])

        click.echo(' '.join(sorted(repos)))
