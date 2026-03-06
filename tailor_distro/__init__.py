__version__ = '0.0.0'

import argparse
import json
import pathlib
import re
import subprocess
import sys
try:
    import yaml
except ModuleNotFoundError:
    pass

from collections import namedtuple
from typing import Iterable, List


SCHEME_S3 = "s3://"
ARCH_LIST = ["amd64", "armhf", "i386"]
S3_CHUNK_SIZE = 1000
DEB_S3_BIN = "deb-s3"

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
    if kwargs.pop('capture_output', False):
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.PIPE
    return subprocess.run(cmd, check=True, *args, **kwargs)


def gpg_import_keys(keys: Iterable[pathlib.Path]) -> None:
    """Import gpg key from path."""
    for key in keys:
        run_command(['gpg', '--import', str(key)])


def get_gpg_key_id(homedir: str = "/home/tailor/.gnupg") -> str:
    """Get gpg's key id."""
    output = run_command([
        "gpg",
        "--homedir",
        homedir,
        "--list-keys",
        "--with-colons",
        "--fingerprint",
        "--with-subkey-fingerprints"
    ], capture_output=True)
    lines = output.stdout.decode('utf-8').split('\n')

    for line in lines:
        if not line.startswith("fpr"):
            continue
        fingerprint = line.split(":")[9]
        return fingerprint

    raise Exception("Could not get fingerprint for gpg key")


def aptly_configure(apt_repo, release_label):
    bucket_name = get_bucket_name(apt_repo)
    aptly_endpoint = f"s3:{bucket_name}:{release_label}/ubuntu/"

    aptly_config = {
        "gpgProvider": "gpg",
        "gpgDisableVerify": False,
        "gpgDisableSign": False,
        "dependencyFollowSuggests": True,
        "dependencyFollowRecommends": True,
        "dependencyFollowAllVariants": True,
        "S3PublishEndpoints": {
            bucket_name: {
                "region": "us-east-1",
                "bucket": bucket_name,
                "acl": "private",
                "debug": False
            }
        }
    }

    with open(pathlib.Path.home() / ".aptly.conf", mode='w') as aptly_config_file:
        json.dump(aptly_config, aptly_config_file)

    return aptly_endpoint


def deb_s3_common_args(apt_repo: str, os_name: str, os_version: str, release_label: str) -> List[str]:
    bucket_name = get_bucket_name(apt_repo)
    return [
        f'--bucket={bucket_name}',
        f'--origin={apt_repo}',
        f'--prefix={release_label}/{os_name}',
        f'--codename={os_version}',
        f'--suite={os_version}',
    ]


whitespace_regex = re.compile(r'\s+')
PackageEntry = namedtuple("PackageEntry", "name version arch")

def deb_s3_list_packages(common_args: List[str]) -> List[PackageEntry]:
    entries = []
    command = [
        DEB_S3_BIN, 'list',
    ]
    command.extend(common_args)
    stdout = run_command(command, stdout=subprocess.PIPE).stdout.decode()
    package_lines = stdout.strip().splitlines()
    for line in package_lines:
        print(f"Adding {line}")
        entries.append(PackageEntry(*whitespace_regex.split(line)))
    #print(package_lines)
    return entries


def deb_s3_upload_packages(package_files: Iterable[pathlib.Path], visibility: str, common_args: Iterable[str], key_homedir: str, dry_run: bool = False):
    if dry_run:
        gpg_key = None
    else:
        gpg_key = get_gpg_key_id(key_homedir)
    command = [
        DEB_S3_BIN, 'upload',
        *map(str, package_files),
        f'--visibility={visibility}', f'--sign={gpg_key}', '--gpg-provider=gpg', '--preserve-versions'
    ]
    command.extend(common_args)

    if dry_run:
        print(' '.join(command))
    else:
        run_command(command)


def deb_s3_delete_packages(packages: Iterable[PackageEntry], visibility: str, common_args: Iterable[str], key_homedir: str, dry_run: bool = False):
    if dry_run:
        gpg_key = None
    else:
        gpg_key = get_gpg_key_id(key_homedir)

    packages_and_versions = [f"{pkg.name}={pkg.version}" for pkg in packages]

    command = [
        DEB_S3_BIN, 'delete_batch', *packages_and_versions,
        '--arch=amd64', '--do-package-remove',
        f'--visibility={visibility}', f'--sign={gpg_key}', '--gpg-provider=gpg'
    ]
    command.extend(common_args)
    if dry_run:
        print(' '.join(command))
    else:
        run_command(command)

def deb_s3_verify(common_args: Iterable[str], key_homedir: str, dry_run: bool = False):
    if dry_run:
        gpg_key = None
    else:
        gpg_key = get_gpg_key_id(key_homedir)

    command = [
        'deb-s3', 'verify',
        '--visibility=private', f'--sign={gpg_key}', '--gpg-provider=gpg', '--fix-manifests'
    ]
    command.extend(common_args)
    run_command(command)
