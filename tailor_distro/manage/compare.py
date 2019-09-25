#!/usr/bin/python3
import click
import re

from collections import defaultdict

from .base import BaseVerb


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

    def execute(self, repositories, rosdistro_path, distro, upstream_index, upstream_distro, missing, raw):
        super().execute(rosdistro_path, distro)
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

        diff_url = build_diff(
            upstream=get_url(self.upstream_distro.repositories.get(repo)),
            internal=get_url(self.internal_distro.repositories.get(repo)))

        if diff_url:
            diff['url'] = diff_url
            # version diffs are meaningless when the repository URL is different (e.g. a fork)
            return diff

        diff_version = build_diff(
            upstream=get_version(self.upstream_distro.repositories.get(repo)),
            internal=get_version(self.internal_distro.repositories.get(repo)))

        if diff_version:
            diff['version'] = diff_version

        return diff


def get_url(repo):
    return repo and repo.source_repository and repo.source_repository.url


VERSION_TRIM = re.compile("-.+")


def get_version(repo):
    version = repo and repo.release_repository and repo.release_repository.version
    if version:
        version = VERSION_TRIM.sub('', version)
    return version


def build_diff(internal, upstream):
    if internal != upstream:
        return {
            'upstream': upstream,
            'internal': internal,
        }
