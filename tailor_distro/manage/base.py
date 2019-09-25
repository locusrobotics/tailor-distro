#!/usr/bin/python3
import abc
import click
import difflib
import github
import json
import re
import pathlib
import yaml

from urllib.parse import urlsplit, urlunsplit
from urllib.error import HTTPError
from rosdistro import get_index, get_distribution, Index
from rosdistro.distribution_file import create_distribution_file
from rosdistro.writer import yaml_from_distribution_file


def get_github_token():
    try:
        token_path = pathlib.Path('~/.git-tokens').expanduser()
        return json.load(token_path.open()).get('github', None)
    except Exception:
        # TODO(pbovbel) Add interactive auth creation?
        click.echo(click.style(f'Unable to find a github token at {token_path}', fg='red'), err=True)
        raise


def get_github_client():
    return github.Github(get_github_token())


def insert_auth_token(url, token):
    parts = urlsplit(url)
    parts._replace(netloc=token + '@' + parts.netloc)
    return urlunsplit(parts)


RAW_GH_PATTERN = re.compile('https://raw.githubusercontent.com/(?P<repo>[^/]+/[^/]+)/(?P<branch>[^/]+)/(?P<path>.+)')


def get_distro_from_index(index, dist_name, type_='distribution'):
    """
       Portion of the logic from rosdistro.get_distribution
    """
    if dist_name not in index.distributions.keys():
        valid_names = ', '.join(sorted(index.distributions.keys()))
        raise RuntimeError("Unknown release: '{0}'. Valid release names are: {1}".format(dist_name, valid_names))
    dist = index.distributions[dist_name]
    if type_ not in dist.keys():
        raise RuntimeError('unknown release type "%s"' % type_)

    return dist[type_]


class BaseVerb(metaclass=abc.ABCMeta):
    """Abstract base class for all distro management verbs."""

    @abc.abstractmethod
    def execute(self, rosdistro_path, distro):
        m = RAW_GH_PATTERN.match(rosdistro_path)
        if m:
            gh = get_github_client()
            self.repo = gh.get_repo(m.group('repo'))
            self.path = m.group('path')
            self.branch = m.group('branch')

            self.rosdistro_path = pathlib.Path(self.path)

            try:
                self.internal_index = get_index(rosdistro_path)
                self.internal_distro = get_distribution(self.internal_index, distro)
            except HTTPError:
                # Only needed for private github repositories
                distro_folder = self.rosdistro_path.parent
                self.internal_index = Index(self.load_distro_file(self.path), str(distro_folder))

                dist_url = get_distro_from_index(self.internal_index, distro)
                if not isinstance(dist_url, list):
                    data = self.load_distro_file(dist_url)
                else:
                    data = []
                    for u in dist_url:
                        data.append(self.load_distro_file(str(u)))
                self.internal_distro = create_distribution_file(distro, data)
        else:
            self.repo = None

            self.rosdistro_path = pathlib.Path(rosdistro_path)
            if not self.rosdistro_path.exists():
                if 'http' in rosdistro_path:
                    raise RuntimeError(f'Cannot use non-Github path ({rosdistro_path}) at this time.')
                else:
                    raise RuntimeError(f'Cannot parse rosdistro_path ({rosdistro_path} as github path or '
                                       'find it as local file.')
            internal_index_path = (self.rosdistro_path / 'rosdistro' / 'index.yaml').resolve().as_uri()
            self.internal_index = get_index(internal_index_path)
            self.internal_distro = get_distribution(self.internal_index, distro)

        self.internal_distro_file = self.internal_index.distributions[distro]['distribution'][-1]

    def load_distro_file(self, path):
        if self.repo:
            git_file = self.repo.get_contents(path, self.branch)
            yaml_str = git_file.decoded_content.decode()
        else:
            path_obj = self.rosdistro_path / path
            yaml_str = path_obj.open()
        return yaml.safe_load(yaml_str)

    def register_arguments(self, parser):
        parser.set_defaults(verb=self.execute)
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")
        # TODO(pbovbel) Use path relative to package?
        parser.add_argument('--rosdistro-path', default='.', help="Index URL override")

    def repositories_arg(self, parser):
        parser.add_argument('repositories', nargs='*', metavar='REPO', help="Repositories to operate on")

    def upstream_arg(self, parser):
        parser.add_argument('--upstream-distro', help="Upstream distribution override")
        parser.add_argument('--upstream-index', help="Upstream index URL override")

    def load_upstream(self, distro, upstream_index, upstream_distro):
        recipes = self.load_distro_file('config/recipes.yaml')
        try:
            info = recipes['common']['distributions'][distro]['upstream']
        except KeyError:
            info = None
        index = get_index(upstream_index if upstream_index is not None else info['url'])
        self.upstream_distro = get_distribution(
            index,
            upstream_distro if upstream_distro is not None else info['name']
        )

    def write_internal_distro(self, message='[no message]'):
        new_contents = yaml_from_distribution_file(self.internal_distro)

        if self.repo:
            git_file = self.repo.get_contents(self.path, self.branch)
            original_contents = git_file.decoded_content.decode()

            print('\n'.join(difflib.unified_diff(original_contents.split('\n'), new_contents.split('\n'), lineterm='',
                                                 fromfile=self.path, tofile='%s (modified)' % self.path)))

            response = ''
            try:
                while not response or response[0] not in 'yn':
                    response = input('Make commit "{}"? (y/n): '.format(message)).strip().lower()
            except KeyboardInterrupt:
                print()
                response = 'n'
            except EOFError:
                print()
                response = 'n'

            if response[0] == 'n':
                print('Maybe later.')
                return

            self.repo.update_file(self.path, message, new_contents, git_file.sha, branch=self.branch)
        else:
            distro_file_path = pathlib.Path(self.internal_distro_file[len('file://'):])
            distro_file_path.write_text(new_contents)
