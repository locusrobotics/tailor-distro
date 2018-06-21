#!/usr/bin/python3
import argparse
import bisect
import pathlib
import re
import subprocess
import sys

from typing import Iterable, Dict, Set, Optional  # flake8: noqa

from collections import defaultdict, namedtuple
from datetime import datetime, timedelta


def gpg_import_key(keys: Iterable[pathlib.Path]) -> None:
    """Import gpg key from path."""
    for key in keys:
        cmd_import = ['gpg1', '--import', str(key)]
        print(' '.join(cmd_import))
        subprocess.run(cmd_import, check=True)


def aptly_create_repo(repo_name: str) -> bool:
    """Try to create an aptly repo."""
    try:
        cmd_create = ['aptly', 'repo', 'create', repo_name]
        print(' '.join(cmd_create))
        subprocess.run(cmd_create, check=True, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        expected_error = 'local repo with name {} already exists'.format(repo_name)
        if expected_error not in e.stderr.decode():
            raise
        print(expected_error)

    return False


def aptly_add_package(repo_name: str, package: pathlib.Path) -> None:
    """Add a package to an aptly repo."""
    cmd_add = ['aptly', 'repo', 'add', repo_name, str(package)]
    print(' '.join(cmd_add))
    subprocess.run(cmd_add, check=True)


def aptly_remove_packages(repo_name: str, package_versions: Dict[str, str]) -> None:
    """Remove packages from an aptly repo."""
    for name, version in package_versions:
        package_query = "Name (= {}), Version (% {}*)".format(name, version)
        cmd_remove = ['aptly', 'repo', 'remove', repo_name, package_query]
        print(' '.join(cmd_remove))
        subprocess.run(cmd_remove, check=True)

    cmd_cleanup = ['aptly', 'db', 'cleanup', '-verbose']
    print(' '.join(cmd_cleanup))
    subprocess.run(cmd_cleanup, check=True)


def aptly_publish_repo(repo_name: str, release_track: str, endpoint: str, new_repo: bool = True) -> None:
    """Publish an aptly repo to an endpoint."""
    if new_repo:
        cmd_publish = [
            'aptly', 'publish', 'repo', '-distribution={}'.format(release_track), repo_name, endpoint
        ]
    else:
        cmd_publish = [
            'aptly', 'publish', 'update', release_track, endpoint
        ]
    print(' '.join(cmd_publish))
    subprocess.run(cmd_publish, check=True)


def aptly_get_packages(repo_name: str) -> Iterable[str]:
    """Get list of packages from aptly repo."""
    cmd_search = ['aptly', 'repo', 'search', repo_name]
    print(' '.join(cmd_search))
    return subprocess.run(cmd_search, check=True, stdout=subprocess.PIPE).stdout.decode().strip().splitlines()


name_regex = re.compile('^[^_]*')
version_regex = re.compile('(?<=\_)([0-9\.]*)')
version_date_format = '%Y%m%d.%H%M%S'
PackageVersion = namedtuple("PackageVersion", "package version")


def build_deletion_list(packages: Iterable[str], num_to_keep: int = None, date_to_keep: datetime = None):
    """Filter a debian package list down to packages to be deleted given some rules.
    :param packages: package names to filter
    :param num_to_keep: number of packages of the same to keep
    :param date_to_keep: date before which to discard packages
    :return: list of package names to delete
    """
    package_versions = defaultdict(set)  # type: Dict[str, Set[str]]

    for package in packages:
        name = name_regex.search(package).group()  # type: ignore
        version = version_regex.search(package).group()  # type: ignore
        package_versions[name].add(version)

    delete_packages = set()

    for package_name, version_set in package_versions.items():
        delete_versions = set()
        sorted_versions = sorted(version_set)

        if num_to_keep:
            delete_versions.update(sorted_versions[:-num_to_keep])
        if date_to_keep:
            date_string = date_to_keep.strftime(version_date_format)
            oldest_to_keep = bisect.bisect_left(sorted_versions, date_string)
            delete_versions.update(sorted_versions[:oldest_to_keep])

        delete_packages.update({PackageVersion(package_name, package_version) for package_version in delete_versions})

    return delete_packages


def publish_packages(packages: Iterable[pathlib.Path], release_track: str, endpoint: str,
                     keys: Iterable[pathlib.Path] = [], days_to_keep: int = None, num_to_keep: int = None) -> None:
    """Publish packages in a release track to and endpoint using aptly. Optionally provided are GPG keys to use for
    signing, and a cleanup policy (days/number of packages to keep).
    :param packages: Package paths to publish.
    :param release_track: Release track of apt repo to target.
    :param endpoint: Aptly endpoint where to publish release track.
    :param keys: (Optional) GPG keys to use while publishing.
    :param days_to_keep: (Optional) Age in days at which old packages should be cleaned up.
    :param num_to_keep: (Optional) Quantity of old packages to keep.
    """
    if keys:
        gpg_import_key(keys)

    repo_name = "locus-{}-main".format(release_track)

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

    aptly_publish_repo(repo_name, release_track, endpoint, new_repo)


def main():
    parser = argparse.ArgumentParser(description=publish_packages.__doc__)
    parser.add_argument('packages', type=pathlib.Path, nargs='+')
    parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--endpoint', type=str, required=True)
    parser.add_argument('--keys', type=pathlib.Path, nargs='+')
    parser.add_argument('--days-to-keep', type=int)
    parser.add_argument('--num-to-keep', type=int)
    args = parser.parse_args()

    sys.exit(publish_packages(**vars(args)))

if __name__ == '__main__':
    main()
