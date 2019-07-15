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

    def execute(self, distro, rosdistro_path, name_pattern, url_pattern, pinned, unpinned):
        super().execute(rosdistro_path, distro)
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
                if data.release_repository and data.release_repository.version is not None
            }
        elif unpinned:
            repos &= {
                repo for repo, data in self.internal_distro.repositories.items()
                if data.release_repository is None or data.release_repository.version is None
            }

        click.echo(' '.join(sorted(repos)))
