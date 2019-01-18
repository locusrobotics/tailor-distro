#!/usr/bin/python3
import argparse
import sys

from .base import BaseVerb
from .compare import CompareVerb  # noqa
from .import_ import ImportVerb  # noqa
from .pin import PinVerb  # noqa
from .query import QueryVerb  # noqa
from .release import ReleaseVerb  # noqa


def main():
    parser = argparse.ArgumentParser(description="Helpful tools for managing a rosdistro for tailor.")
    subparsers = parser.add_subparsers(dest='verb', help='Subcommand')

    for verb in [verb() for verb in BaseVerb.__subclasses__()]:
        verb.register_arguments(subparsers.add_parser(verb.name, help=verb.__doc__))

    args = vars(parser.parse_args())

    verb = args.pop('verb')

    if verb is not None:
        sys.exit(verb(**args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
