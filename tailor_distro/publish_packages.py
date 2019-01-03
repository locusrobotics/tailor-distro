#!/usr/bin/python3
import argparse
import bisect
import pathlib
import re
import subprocess
import sys

from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from typing import Iterable, Dict, Set, Optional

from . import get_bucket_name, aptly_configure, run_command, gpg_import_keys


def aptly_create_repo(repo_name: str) -> bool:
    """Try to create an aptly repo."""
    try:
        run_command(['aptly', 'repo', 'create', repo_name])
        return True
    except subprocess.CalledProcessError as e:
        expected_error = 'already exists'
        if expected_error not in e.stderr.decode():
            raise
        print(expected_error)

    return False


def aptly_add_package(repo_name: str, package: pathlib.Path) -> None:
    """Add a package to an aptly repo."""
    run_command(['aptly', 'repo', 'add', repo_name, str(package)])


def aptly_remove_packages(repo_name: str, package_versions: Dict[str, str]) -> None:
    """Remove packages from an aptly repo."""
    for name, version in package_versions:
        package_query = f"Name (= {name}), Version (% {version}*)"
        run_command(['aptly', 'repo', 'remove', repo_name, package_query])

    run_command(['aptly', 'db', 'cleanup', '-verbose'])


def aptly_publish_repo(repo_name: str, release_track: str, endpoint: str, distribution: str,
                       new_repo: bool = True) -> None:
    """Publish an aptly repo to an endpoint."""
    if new_repo:
        cmd_publish = [
            'aptly', 'publish', 'repo', f'-distribution={distribution}', f'-component=main',
            '-label=distro', repo_name, endpoint
        ]
    else:
        cmd_publish = [
            'aptly', 'publish', 'update', distribution, endpoint
        ]
    run_command(cmd_publish)


def aptly_get_packages(repo_name: str) -> Iterable[str]:
    """Get list of packages from aptly repo."""
    return run_command(
        ['aptly', 'repo', 'search', repo_name], stdout=subprocess.PIPE
    ).stdout.decode().strip().splitlines()


name_regex = re.compile('^[^_]*')
version_regex = re.compile(r'(?<=\_)([0-9\.]*)')
version_date_format = '%Y%m%d.%H%M%S'
PackageVersion = namedtuple("PackageVersion", "package version")


def build_deletion_list(packages: Iterable[str], num_to_keep: int = None, date_to_keep: datetime = None):
    """Filter a debian package list down to packages to be deleted given some rules.
    :param packages: package names to filter
    :param num_to_keep: number of packages of the same to keep
    :param date_to_keep: date before which to discard packages
    :return: list of package names to delete
    """
    package_versions: Dict[str, Set[str]] = defaultdict(set)

    for package in packages:
        name = name_regex.search(package).group()  # type: ignore
        version = version_regex.search(package).group()  # type: ignore
        package_versions[name].add(version)

    delete_packages = set()

    for package_name, version_set in package_versions.items():
        delete_versions = set()
        sorted_versions = sorted(version_set)

        if num_to_keep is not None:
            # pylint: disable=E1130
            delete_versions.update(sorted_versions[:-num_to_keep])
        if date_to_keep is not None:
            date_string = date_to_keep.strftime(version_date_format)
            oldest_to_keep = bisect.bisect_left(sorted_versions, date_string)
            delete_versions.update(sorted_versions[:oldest_to_keep])

        delete_packages.update({PackageVersion(package_name, package_version) for package_version in delete_versions})

    return delete_packages


def publish_packages(packages: Iterable[pathlib.Path], release_track: str, apt_repo: str, distribution: str,
                     keys: Iterable[pathlib.Path] = [],
                     days_to_keep: int = None, num_to_keep: int = None) -> None:
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
    aptly_endpoint = aptly_configure(bucket_name, release_track)

    repo_name = f"{bucket_name}-{release_track}-{distribution}"

    new_repo = aptly_create_repo(repo_name)

    for package in packages:
        aptly_add_package(repo_name, package)

    if days_to_keep is not None:
        date_to_keep: Optional[datetime] = datetime.now() - timedelta(days=days_to_keep)
    else:
        date_to_keep = None

    aptly_packages = aptly_get_packages(repo_name)
    to_delete = build_deletion_list(aptly_packages, num_to_keep, date_to_keep)
    aptly_remove_packages(repo_name, to_delete)

    aptly_publish_repo(repo_name, release_track, aptly_endpoint, distribution, new_repo)


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
