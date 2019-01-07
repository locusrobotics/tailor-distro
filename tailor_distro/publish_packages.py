#!/usr/bin/python3
import argparse
import bisect
import pathlib
import sys

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, Dict, Set, Optional, Tuple

from . import gpg_import_keys, PackageEntry, \
              deb_s3_common_args, deb_s3_list_packages, deb_s3_upload_packages, deb_s3_delete_packages


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

    common_args = deb_s3_common_args(apt_repo, 'ubuntu', distribution, release_track)

    deb_s3_upload_packages(packages, 'private', common_args)

    if days_to_keep is not None:
        date_to_keep: Optional[datetime] = datetime.now() - timedelta(days=days_to_keep)
    else:
        date_to_keep = None

    remote_packages = deb_s3_list_packages(common_args)
    to_delete = build_deletion_list(remote_packages, distribution, num_to_keep, date_to_keep)
    deb_s3_delete_packages(to_delete, 'private', common_args)


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
