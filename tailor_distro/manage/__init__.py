#!/usr/bin/python3
import argparse
import click
import github
import json
import pathlib
import sys

from .compare import CompareVerb
from .import_ import ImportVerb
from .pin import PinVerb
from .query import QueryVerb
from .release import ReleaseVerb


def get_github_client():
    # TODO(pbovbel) Add interactive auth creation?
    try:
        token_path = pathlib.Path('~/.git-tokens').expanduser()
        github_token = json.load(token_path.open()).get('github', None)
        return github.Github(github_token)
    except Exception:
        click.echo(click.style(f'Unable to find your github token at {token_path}', fg='red'), err=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="TODO")
    subparsers = parser.add_subparsers(dest='verb', help='Subcommand')

    for verb in [verb() for verb in [CompareVerb, ImportVerb, PinVerb, QueryVerb, ReleaseVerb]]:
        verb.register_arguments(subparsers.add_parser(verb.name, help=verb.__doc__))

    args = vars(parser.parse_args())

    verb = args.pop('verb')

    if verb is not None:
        sys.exit(verb(**args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
