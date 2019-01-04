__version__ = '0.0.0'

import argparse
import pathlib
import subprocess
import sys
import yaml

from typing import Iterable


SCHEME_S3 = "s3://"


class YamlLoadAction(argparse.Action):
    def __init__(self, option_strings, dest, nargs=None, **kwargs):
        if nargs is not None:
            raise ValueError("Only supports a single arg, nargs not allowed")
        super(YamlLoadAction, self).__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, value, option_string=None):
        setattr(namespace, self.dest, yaml.safe_load(pathlib.Path(value).open()))


def get_bucket_name(apt_repo):
    assert(apt_repo.startswith(SCHEME_S3))
    return apt_repo[len(SCHEME_S3):]


def run_command(cmd, *args, **kwargs):
    print(' '.join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=True, *args, **kwargs)


def gpg_import_keys(keys: Iterable[pathlib.Path]) -> None:
    """Import gpg key from path."""
    for key in keys:
        run_command(['gpg1', '--import', str(key)])
