#!/usr/bin/python3
import abc
import click
import github
import json
import pathlib

from urllib.parse import urlsplit, urlunsplit


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
    parts = parts._replace(netloc=token + '@' + parts.netloc)
    return urlunsplit(parts)


class BaseVerb(metaclass=abc.ABCMeta):
    """Abstract base class for all distro management verbs."""

    @abc.abstractmethod
    def execute(self, rosdistro_repo):
        self.rosdistro_repo = rosdistro_repo

    def register_arguments(self, parser):
        parser.set_defaults(verb=self.execute)
        parser.add_argument('--distro', required=True, help="Distribution on which to operate")
        # TODO(pbovbel) Use path relative to package?
        parser.add_argument('--rosdistro-path', default='.', help="Index URL override")
        parser.add_argument('--rosdistro-url', help="Index URL override via Github")
        parser.add_argument('--rosdistro-branch', help="Branch of rosdistro to operate on")

    def repositories_arg(self, parser):
        parser.add_argument('repositories', nargs='*', metavar='REPO', help="Repositories to operate on")

    def upstream_arg(self, parser):
        parser.add_argument('--upstream-distro', help="Upstream distribution override")
        parser.add_argument('--upstream-index', help="Upstream index URL override")
