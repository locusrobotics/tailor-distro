#!/usr/bin/python3
import argparse
import pathlib
import sys
import re

from datetime import datetime, timedelta
from typing import Iterable, Dict, Set, Optional, Tuple, List

from . import gpg_import_keys, PackageEntry, \
    deb_s3_common_args, deb_s3_list_packages, deb_s3_upload_packages, deb_s3_delete_packages


version_date_format = '%Y%m%d.%H%M%S'

package_pattern = re.compile(
    r'^(?P<version>\d+\.\d+\.\d+)-'
    r'(?P<date>\d{8}\.\d{6})\+git'
    r'(?P<sha>[0-9a-fA-F]+)$'
)

bundle_pattern = re.compile(
    r'^(?P<version>\d+\.\d+\.\d+)\+'
    r'(?P<date>\d{8}\.\d{6})'
    r'(?P<codename>jammy|noble)$'
)


def parse_version(version: str):
    # There's two possibilities here:
    #  - Individual ROS packages (<ros_version>-<date>+git<sha>)
    #  - Bundle metapackage (<version>+<date><distro>)
    match = package_pattern.match(version)
    if match:
        version = match.groupdict()["date"]
    else:
        match = bundle_pattern.match(version)
        if match:
            version = match.groupdict()["date"]
        else:
            raise Exception(f"Can't parse version {version}")

    return version


def build_deletion_list(packages: Iterable[PackageEntry], distribution: str,
                        num_to_keep: int = None, date_to_keep: datetime = None):
    """Filter a debian package list down to packages to be deleted given some rules.
    :param packages: packages to filter
    :param distribution: distribution name to strip from version
    :param num_to_keep: number of packages of the same to keep
    :param date_to_keep: date before which to discard packages
    :return: list of package names to delete
    """
    package_versions: Dict[Tuple[str, str], List[PackageEntry]] = {}

    for package in packages:
        if (package.name, package.arch) not in package_versions:
            package_versions[(package.name, package.arch)] = [package]
        else:
            package_versions[(package.name, package.arch)].append(package)

    delete_packages: Set[PackageEntry] = set()

    for (name, arch), version_set in package_versions.items():
        versions = [p.version for p in version_set]
        sorted_versions = sorted(versions)

        if num_to_keep is not None:
            # pylint: disable=E1130
            delete_packages.update(sorted_versions[:-num_to_keep])
        if date_to_keep is not None:
            for version in sorted_versions:
                version_string = parse_version(version)
                version_time = datetime.strptime(version_string, version_date_format)

                if version_time < date_to_keep:
                    delete_packages.add(PackageEntry(name, version, arch))

    return delete_packages


def publish_packages(packages: Iterable[pathlib.Path], release_label: str, apt_repo: str, distribution: str,
                     keys: Iterable[pathlib.Path] = [], days_to_keep: int = None, num_to_keep: int = None,
                     dry_run: bool = False) -> None:
    """Publish packages in a release label to and endpoint using aptly. Optionally provided are GPG keys to use for
    signing, and a cleanup policy (days/number of packages to keep).
    :param packages: Package paths to publish.
    :param release_label: Release label of apt repo to target.
    :param apt_repo: Apt repo where to publish release label.
    :param distribution: Package distribution to publish.
    :param keys: (Optional) GPG keys to use while publishing.
    :param days_to_keep: (Optional) Age in days at which old packages should be cleaned up.
    :param num_to_keep: (Optional) Quantity of old packages to keep.
    """
    if keys:
        gpg_import_keys(keys)

    common_args = deb_s3_common_args(apt_repo, 'ubuntu', distribution, release_label)

    deb_s3_upload_packages(packages, 'private', common_args, dry_run)

    if days_to_keep is not None:
        date_to_keep: Optional[datetime] = datetime.now() - timedelta(days=days_to_keep)
    else:
        date_to_keep = None

    remote_packages = deb_s3_list_packages(common_args)
    to_delete = build_deletion_list(remote_packages, distribution, num_to_keep, date_to_keep)
    deb_s3_delete_packages(to_delete, 'private', common_args, dry_run)


def main():
    parser = argparse.ArgumentParser(description=publish_packages.__doc__)
    parser.add_argument('packages', type=pathlib.Path, nargs='+')
    parser.add_argument('--release-label', type=str, required=True)
    parser.add_argument('--apt-repo', type=str, required=True)
    parser.add_argument('--distribution', type=str, required=True)
    parser.add_argument('--keys', type=pathlib.Path, nargs='+')
    parser.add_argument('--days-to-keep', type=int)
    parser.add_argument('--num-to-keep', type=int)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    sys.exit(publish_packages(**vars(args)))


if __name__ == '__main__':
    main()
