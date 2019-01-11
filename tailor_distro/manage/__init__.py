#!/usr/bin/python3
import argparse
import sys

from .compare import CompareVerb
from .import_ import ImportVerb
from .pin import PinVerb
from .query import QueryVerb


def main():
    parser = argparse.ArgumentParser(description="TODO")
    subparsers = parser.add_subparsers(dest='verb', help='Subcommand')

    for verb in [verb() for verb in [CompareVerb, ImportVerb, PinVerb, QueryVerb]]:
        verb.register_arguments(subparsers.add_parser(verb.name, help=verb.__doc__))

    args = vars(parser.parse_args())

    verb = args.pop('verb')

    if verb is not None:
        sys.exit(verb(**args))
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
