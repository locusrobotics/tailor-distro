#!/usr/bin/python3
import argparse
import sys

from .base import BaseVerb
from .compare import CompareVerb  # noqa
from .import_ import ImportVerb  # noqa
from .pin import PinVerb  # noqa
from .query import QueryVerb  # noqa
from .query_release import QueryReleaseVerb  # noqa
from .release import ReleaseVerb  # noqa
from .rosdistro_repo import LocalROSDistro, RemoteROSDistro


def main():
    parser = argparse.ArgumentParser(description="Helpful tools for managing a rosdistro for tailor.")
    subparsers = parser.add_subparsers(dest='verb', help='Subcommand')

    for verb in [verb() for verb in BaseVerb.__subclasses__()]:
        verb.register_arguments(subparsers.add_parser(verb.name, help=verb.__doc__))

    args = vars(parser.parse_args())

    # TODO(dlu): Maybe switch to add_mutually_exclusive_group
    if args['rosdistro_path'] != '.' and args['rosdistro_url']:
        raise RuntimeError('Cannot specify rosdistro using both path and url.')

    distro_name = args.pop('distro')

    if args['rosdistro_url']:
        rosdistro_repo = RemoteROSDistro(args.pop('rosdistro_url'), args.pop('rosdistro_branch'), distro_name)
        args.pop('rosdistro_path')
    else:
        rosdistro_repo = LocalROSDistro(args.pop('rosdistro_path'), distro_name)
        args.pop('rosdistro_url')
        args.pop('rosdistro_branch')

    verb = args.pop('verb')

    if verb is not None:
        sys.exit(verb(rosdistro_repo=rosdistro_repo, **args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
