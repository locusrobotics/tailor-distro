#!/usr/bin/python3
import abc
import click
import difflib
import github
import json
import os
import re
import pathlib
import yaml

from urllib.parse import urlsplit, urlunsplit
from urllib import HTTPError
from rosdistro import get_index, get_index_url, get_distribution, Index
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


def _load_github_helper(url):
    m = RAW_GH_PATTERN.match(url)
    if not m:
        raise RuntimeError('Cannot parse raw github url: {}'.format(url))
    gh = get_github_client()
    repo = gh.get_repo(m.group('repo'))
    return repo, m.group('path'), m.group('branch')


def load_github_file(url):
    repo, path, branch = _load_github_helper(url)
    git_file = repo.get_contents(path, branch)
    yaml_str = git_file.decoded_content.decode()
    return yaml.safe_load(yaml_str)


def write_github_file(url, new_contents, message='[no message given]'):
    repo, path, branch = _load_github_helper(url)
    git_file = repo.get_contents(path, branch)
    original_contents = git_file.decoded_content.decode()

    print('\n'.join(difflib.unified_diff(original_contents.split('\n'), new_contents.split('\n'), lineterm='',
                                         fromfile=path, tofile='%s (modified)' % path)))

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

    repo.update_file(path, message, new_contents, git_file.sha, branch=branch)


def get_private_index(internal_index_path):
    """
       Version of rosdistro.get_index that can load from a private repository
    """
    data = load_github_file(internal_index_path)
    base_url = os.path.dirname(internal_index_path)
    return Index(data, base_url)


def get_private_distro(index, dist_name, type_='distribution'):
    """
        Version of rosdistro.get_distribution that can load from a private repository
    """
    if dist_name not in index.distributions.keys():
        valid_names = ', '.join(sorted(index.distributions.keys()))
        raise RuntimeError("Unknown release: '{0}'. Valid release names are: {1}".format(dist_name, valid_names))
    dist = index.distributions[dist_name]
    if type_ not in dist.keys():
        raise RuntimeError('unknown release type "%s"' % type_)
    url = dist[type_]

    if not isinstance(url, list):
        data = load_github_file(url)
    else:
        data = []
        for u in url:
            data.append(load_github_file(u))
    return create_distribution_file(dist_name, data)


class BaseVerb(metaclass=abc.ABCMeta):
    """Abstract base class for all distro management verbs."""

    @abc.abstractmethod
    def execute(self, rosdistro_path, distro):
        self.rosdistro_path = rosdistro_path
        index_path = rosdistro_path / 'rosdistro' / 'index.yaml'
        if index_path.exists():
            internal_index_path = index_path.resolve().as_uri()
        else:
            internal_index_path = get_index_url()

        try:
            self.internal_index = get_index(internal_index_path)
            self.internal_distro = get_distribution(self.internal_index, distro)
        except HTTPError:
            self.internal_index = get_private_index(internal_index_path)
            self.internal_distro = get_private_distro(self.internal_index, distro)

        self.internal_distro_file = self.internal_index.distributions[distro]['distribution'][-1]

    def register_arguments(self, parser):
        parser.set_defaults(verb=self.execute)
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")
        # TODO(pbovbel) Use path relative to package?
        parser.add_argument('--rosdistro-path', type=pathlib.Path, default='.', help="Index URL override")

    def repositories_arg(self, parser):
        parser.add_argument('repositories', nargs='*', metavar='REPO', help="Repositories to operate on")

    def upstream_arg(self, parser):
        parser.add_argument('--upstream-distro', help="Upstream distribution override")
        parser.add_argument('--upstream-index', help="Upstream index URL override")

    def load_upstream(self, distro, upstream_index, upstream_distro):
        recipes = yaml.safe_load((self.rosdistro_path / 'config' / 'recipes.yaml').open())
        try:
            info = recipes['common']['distributions'][distro]['upstream']
        except KeyError:
            info = None
        index = get_index(upstream_index if upstream_index is not None else info['url'])
        self.upstream_distro = get_distribution(
            index,
            upstream_distro if upstream_distro is not None else info['name']
        )

    def write_internal_distro(self):
        new_contents = yaml_from_distribution_file(self.internal_distro)

        m = RAW_GH_PATTERN.match(self.internal_distro_file)
        if not m:
            distro_file_path = pathlib.Path(self.internal_distro_file[len('file://'):])
            distro_file_path.write_text(new_contents)
        else:
            write_github_file(self.internal_distro_file, new_contents)
