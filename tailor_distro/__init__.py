__version__ = '0.0.0'

import argparse
import pathlib
import re
import subprocess
import sys
import yaml

from collections import namedtuple
from typing import Iterable, List


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


def deb_s3_common_args(bucket_name: str, os_name: str, os_version: str, release_track,
                       access_key_id: str, secret_access_key: str) -> List[str]:
    return [
        f'--bucket={bucket_name}',
        f'--prefix={release_track}/{os_name}',
        f'--codename={os_version}',
        f'--access-key-id={access_key_id}',
        f'--secret-access-key={secret_access_key}'
    ]


whitespace_regex = re.compile(r'\s+')
PackageEntry = namedtuple("PackageEntry", "name version arch")


def deb_s3_list_packages(common_args: Iterable[str]) -> List[PackageEntry]:
    command = [
        'deb-s3', 'list',
    ]
    command.extend(common_args)
    stdout = run_command(command, stdout=subprocess.PIPE).stdout.decode()
    package_lines = stdout.strip().splitlines()
    return [PackageEntry(*whitespace_regex.split(line)) for line in package_lines]


def deb_s3_upload_packages(package_files: Iterable[pathlib.Path], visibility: str, common_args: Iterable[str]):
    command = [
        'deb-s3', 'upload',
        ' '.join(str(path) for path in package_files),
        f'--visibility={visibility}', '--sign', '--gpg-provider=gpg1', '--preserve-versions'
    ]
    command.extend(common_args)
    run_command(command)


def deb_s3_delete_packages(packages: Iterable[PackageEntry], common_args: Iterable[str]):
    for package in packages:
        command = [
            'deb-s3', 'delete', package.name,
            f'--versions={package.version}', f'--arch={package.arch}', '--do-package-remove'
        ]
        command.extend(common_args)
        run_command(command)
