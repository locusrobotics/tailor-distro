#!/usr/bin/python3
import argparse
import bisect
import os
import pathlib
import re
import subprocess
import sys

from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from typing import Iterable, Dict, Set, Optional, List, Tuple

from . import get_bucket_name, run_command, gpg_import_keys


def deb_s3_common_args(bucket_name: str, os_name: str, os_version: str, release_track,
                       access_key_id: str, secret_access_key: str) -> List[str]:
    return [
        f'--bucket={bucket_name}',
        f'--prefix={release_track}/{os_name}',
        f'--codename={os_version}',
        f'--access-key-id={access_key_id}',
        f'--secret-access-key={secret_access_key}'
    ]


def deb_s3_upload_packages(package_files: Iterable[pathlib.Path], visibility: str, common_args: Iterable[str]):
    command = [
        'deb-s3', 'upload',
        ' '.join(str(path) for path in package_files),
        f'--visibility={visibility}', '--sign', '--gpg-provider=gpg1', '--preserve-versions'
    ]
    command.extend(common_args)
    run_command(command)


whitespace_regex = re.compile(r'\s*')
PackageEntry = namedtuple("PackageEntry", "name version arch")


def deb_s3_list_packages(common_args: Iterable[str]) -> List[PackageEntry]:
    command = [
        'deb-s3', 'list',
    ]
    command.extend(common_args)
    stdout = run_command(command, stdout=subprocess.PIPE).stdout.decode()
    package_lines = stdout.strip().splitlines()
    return [PackageEntry(*whitespace_regex.split(line)) for line in package_lines]


def deb_s3_delete_packages(packages: Iterable[PackageEntry], common_args: Iterable[str]):
    for package in packages:
        command = [
            'deb-s3', 'delete', package.name,
            f'--versions={package.version}', f'--arch={package.arch}', '--do-package-remove'
        ]
        command.extend(common_args)
        run_command(command)


version_date_format = '%Y%m%d.%H%M%S'


def build_deletion_list(packages: Iterable[PackageEntry], distribution: str,
                        num_to_keep: int = None, date_to_keep: datetime = None):
    """Filter a debian package list down to packages to be deleted given some rules.
    :param packages: packages to filter
    :param distribution: distribution name to strip from version
    :param num_to_keep: number of packages of the same to keep
    :param date_to_keep: date before which to discard packages
    :return: list of package names to delete
    """
    package_versions: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for package in packages:
        # Strip distro name from package version
        assert(package.version.endswith(distribution))
        version = package.version[:-len(distribution)]
        package_versions[(package.name, package.arch)].add(version)

    delete_packages = set()

    for (name, arch), version_set in package_versions.items():
        delete_versions = set()
        sorted_versions = sorted(version_set)

        if num_to_keep is not None:
            # pylint: disable=E1130
            delete_versions.update(sorted_versions[:-num_to_keep])
        if date_to_keep is not None:
            date_string = date_to_keep.strftime(version_date_format)
            oldest_to_keep = bisect.bisect_left(sorted_versions, date_string)
            delete_versions.update(sorted_versions[:oldest_to_keep])

        delete_packages.update({PackageEntry(name, version + distribution, arch) for version in delete_versions})

    return delete_packages


def publish_packages(packages: Iterable[pathlib.Path], release_track: str, apt_repo: str, distribution: str,
                     keys: Iterable[pathlib.Path] = [], days_to_keep: int = None, num_to_keep: int = None) -> None:
    """Publish packages in a release track to and endpoint using aptly. Optionally provided are GPG keys to use for
    signing, and a cleanup policy (days/number of packages to keep).
    :param packages: Package paths to publish.
    :param release_track: Release track of apt repo to target.
    :param apt_repo: Apt repo where to publish release track.
    :param distribution: Package distribution to publish.
    :param keys: (Optional) GPG keys to use while publishing.
    :param days_to_keep: (Optional) Age in days at which old packages should be cleaned up.
    :param num_to_keep: (Optional) Quantity of old packages to keep.
    """
    if keys:
        gpg_import_keys(keys)

    bucket_name = get_bucket_name(apt_repo)

    common_args = deb_s3_common_args(
        bucket_name, 'ubuntu', distribution, release_track,
        os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY']
    )

    deb_s3_upload_packages(packages, 'private', common_args)

    if days_to_keep is not None:
        date_to_keep: Optional[datetime] = datetime.now() - timedelta(days=days_to_keep)
    else:
        date_to_keep = None

    remote_packages = deb_s3_list_packages(common_args)
    to_delete = build_deletion_list(remote_packages, distribution, num_to_keep, date_to_keep)
    deb_s3_delete_packages(to_delete, common_args)


def main():
    parser = argparse.ArgumentParser(description=publish_packages.__doc__)
    parser.add_argument('packages', type=pathlib.Path, nargs='+')
    parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--apt-repo', type=str, required=True)
    parser.add_argument('--distribution', type=str, required=True)
    parser.add_argument('--keys', type=pathlib.Path, nargs='+')
    parser.add_argument('--days-to-keep', type=int)
    parser.add_argument('--num-to-keep', type=int)
    args = parser.parse_args()

    sys.exit(publish_packages(**vars(args)))


if __name__ == '__main__':
    main()
