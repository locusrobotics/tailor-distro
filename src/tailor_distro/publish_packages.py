#!/usr/bin/python3
import argparse
import bisect
import pathlib
import re
import subprocess

from collections import defaultdict, namedtuple
from datetime import datetime, timedelta


def gpg_import_key(keys):
    """Import gpg key from path."""
    for key in keys:
        cmd_import = ['gpg1', '--import', str(key)]
        print(' '.join(cmd_import))
        subprocess.run(cmd_import, check=True)


def aptly_create_repo(repo_name):
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


def aptly_add_package(repo_name, package):
    """Add a package to an aptly repo."""
    cmd_add = ['aptly', 'repo', 'add', repo_name, str(package)]
    print(' '.join(cmd_add))
    subprocess.run(cmd_add, check=True)


def aptly_remove_packages(repo_name, package_versions):
    """Remove packages from an aptly repo."""
    for name, version in package_versions:
        package_query = "Name (= {}), Version (% {}*)".format(name, version)
        cmd_remove = ['aptly', 'repo', 'remove', repo_name, package_query]
        print(' '.join(cmd_remove))
        subprocess.run(cmd_remove, check=True)

    cmd_cleanup = ['aptly', 'db', 'cleanup', '-verbose']
    print(' '.join(cmd_cleanup))
    subprocess.run(cmd_cleanup, check=True)


def aptly_publish_repo(repo_name, release_track, endpoint, new_repo=True):
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


def aptly_get_packages(repo_name):
    """Get list of packages from aptly repo."""
    cmd_search = ['aptly', 'repo', 'search', repo_name]
    print(' '.join(cmd_search))
    return subprocess.run(cmd_search, check=True, stdout=subprocess.PIPE).stdout.decode().strip().splitlines()


name_regex = re.compile('^[^_]*')
version_regex = re.compile('(?<=\_)([0-9\.]*)')
version_date_format = '%Y%m%d.%H%M%S'

PackageVersion = namedtuple("PackageVersion", "package version")


def build_deletion_list(packages, num_to_keep=None, date_to_keep=None):
    """Filter a debian package list down to packages to be deleted given some rules."""
    package_versions = defaultdict(set)

    for package in packages:
        name = name_regex.search(package).group()
        version = version_regex.search(package).group()
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


def main():
    parser = argparse.ArgumentParser(description='Push a set of packages to s3.')
    parser.add_argument('packages', type=pathlib.Path, nargs='+')
    parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--endpoint', type=str, required=True)
    parser.add_argument('--keys', type=pathlib.Path, nargs='+')
    parser.add_argument('--days-to-keep', type=int)
    parser.add_argument('--num-to-keep', type=int)
    args = parser.parse_args()

    if args.keys:
        gpg_import_key(args.keys)

    repo_name = "locus-{}-main".format(args.release_track)

    new_repo = aptly_create_repo(repo_name)

    for package in args.packages:
        aptly_add_package(repo_name, package)

    try:
        date_to_keep = datetime.now() - timedelta(days=args.days_to_keep)
    except TypeError:
        date_to_keep = None

    packages = aptly_get_packages(repo_name)
    to_delete = build_deletion_list(packages, args.num_to_keep, date_to_keep)
    aptly_remove_packages(repo_name, to_delete)

    aptly_publish_repo(repo_name, args.release_track, args.endpoint, new_repo)


if __name__ == '__main__':
    main()
