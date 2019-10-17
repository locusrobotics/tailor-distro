#!/usr/bin/python3
import click

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

    def execute(self, repositories, rosdistro_path, rosdistro_url, rosdistro_branch,
                distro, upstream_index, upstream_distro, missing, raw):
        super().execute(rosdistro_path, rosdistro_url, rosdistro_branch, distro)
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
