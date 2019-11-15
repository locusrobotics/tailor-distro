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
        repos = set()
        for repo in self.rosdistro_repo.get_repo_names():
            if name_pattern is not None and not name_pattern.match(repo):
                continue

            src_repo = self.rosdistro_repo[repo].source_repository
            rel_repo = self.rosdistro_repo[repo].release_repository

            if url_pattern is not None and (src_repo is None or not url_pattern.match(src_repo.url)):
                continue

            if pinned and (rel_repo is None or rel_repo.version is None):
                continue
            elif unpinned and rel_repo is not None and rel_repo.version is not None:
                continue

            repos.add(repo)

        click.echo(' '.join(sorted(repos)))
