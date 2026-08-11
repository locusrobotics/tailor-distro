#!/usr/bin/python3
import argparse
import pathlib
import sys
import re

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Dict, Set, Optional, Tuple, List

from . import gpg_import_keys, PackageEntry, \
    deb_s3_common_args, deb_s3_list_packages, deb_s3_upload_packages, deb_s3_delete_packages


version_date_format = '%Y%m%d.%H%M%S'

package_pattern = re.compile(
    r'^(?:(?P<epoch>\d+):)?(?P<version>.+)-'
    r'(?P<date>\d{8}\.\d{6})\+git'
    r'(?P<sha>[0-9a-fA-F]+)$'
)

bundle_pattern = re.compile(
    r'^(?:(?P<epoch>\d+):)?(?P<version>\d+\.\d+\.\d+)\+'
    r'(?P<date>\d{8}\.\d{6})'
    r'(?P<codename>jammy|noble)$'
)


@dataclass(frozen=True)
class PublishPlan:
    repo_name: str
    packages_to_add: Tuple[pathlib.Path, ...]
    packages_to_delete: Tuple[PackageEntry, ...]
    date_to_keep: Optional[datetime]
    stale_s3_refs_to_delete: Tuple = ()


def parse_version(version: str) -> Optional[str]:
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
            return None

    return version


def build_deletion_list(packages: Iterable[PackageEntry],
                        num_to_keep: Optional[int] = None,
                        date_to_keep: Optional[datetime] = None):
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
        sorted_pkgs = sorted(version_set, key=lambda p: p.version)

        if num_to_keep is not None:
            # pylint: disable=E1130
            delete_packages.update(sorted_pkgs[:-num_to_keep])
        if date_to_keep is not None:
            for pkg in sorted_pkgs:
                version_string = parse_version(pkg.version)
                if version_string is None:
                    continue
                version_time = datetime.strptime(version_string, version_date_format)

                if version_time < date_to_keep:
                    delete_packages.add(PackageEntry(name, pkg.version, arch))

    return delete_packages


def build_publish_plan(packages: Iterable[pathlib.Path], release_label: str,
                       distribution: str,
                       days_to_keep: Optional[int] = None,
                       num_to_keep: Optional[int] = None,
                       existing_packages: Iterable[PackageEntry] = (),
                       s3_refs: Iterable = ()) -> PublishPlan:
    repo_name = f"{release_label}-{distribution}"
    packages_to_add = tuple(packages)
    existing_packages_list = list(existing_packages)

    if days_to_keep is not None:
        date_to_keep: Optional[datetime] = datetime.now() - timedelta(days=days_to_keep)
    else:
        date_to_keep = None

    if num_to_keep is not None or date_to_keep is not None:
        to_delete = tuple(sorted(
            build_deletion_list(existing_packages_list, num_to_keep, date_to_keep),
            key=lambda pkg: (pkg.name, pkg.arch, pkg.version),
        ))
    else:
        to_delete = ()

    stale_s3_to_delete: Tuple = ()

    return PublishPlan(
        repo_name=repo_name,
        packages_to_add=packages_to_add,
        packages_to_delete=to_delete,
        date_to_keep=date_to_keep,
        stale_s3_refs_to_delete=stale_s3_to_delete,
    )


def print_publish_plan(plan: PublishPlan) -> None:
    print(f"Repo: {plan.repo_name}")
    print(f"Packages to add: {len(plan.packages_to_add)}")
    for package_path in plan.packages_to_add:
        print(f"  ADD {package_path}")

    if plan.date_to_keep is not None:
        print(f"Delete packages older than: {plan.date_to_keep.strftime(version_date_format)}")
    else:
        print("Delete packages older than: disabled")

    print(f"Packages to delete: {len(plan.packages_to_delete)}")
    for package_entry in plan.packages_to_delete:
        print(f"  DELETE {package_entry.name}_{package_entry.version}_{package_entry.arch}")

    if plan.stale_s3_refs_to_delete:
        print(f"Stale S3 artifacts to delete: {len(plan.stale_s3_refs_to_delete)}")
        for ref in list(plan.stale_s3_refs_to_delete)[:10]:
            print(f"  DELETE S3 {ref.s3_key}")
        remainder = len(plan.stale_s3_refs_to_delete) - 10
        if remainder > 0:
            print(f"  ... and {remainder} more")
def publish_packages(packages: Iterable[pathlib.Path], release_label: str, apt_repo: str, distribution: str,
                     keys: Iterable[pathlib.Path] = [], days_to_keep: Optional[int] = None,
                     num_to_keep: Optional[int] = None,
                     organization: str = 'locusrobotics',
                     cleanup_stale_s3: bool = False,
                     key_homedir: Optional[str] = None,
                     dry_run: bool = False) -> Optional[PublishPlan]:
    """Publish packages in a release label to an endpoint using deb-s3. Optionally provided are GPG keys to use for
    signing, and a cleanup policy (days/number of packages to keep).
    :param packages: Package paths to publish.
    :param release_label: Release label of apt repo to target.
    :param apt_repo: Apt repo where to publish release label.
    :param distribution: Package distribution to publish.
    :param keys: (Optional) GPG keys to use while publishing.
    :param days_to_keep: (Optional) Age in days at which old packages should be cleaned up.
    :param num_to_keep: (Optional) Quantity of old packages to keep.
    :param organization: (Optional) Package organization prefix to match in remote dry-run discovery.
    """
    common_args = deb_s3_common_args(apt_repo, 'ubuntu', distribution, release_label)
    effective_key_homedir = key_homedir or "/home/tailor/.gnupg"

    if keys:
        gpg_import_keys(keys)

    if packages:
        deb_s3_upload_packages(packages, 'private', common_args, effective_key_homedir, dry_run)

    existing_packages = deb_s3_list_packages(common_args)
    plan = build_publish_plan(
        packages=packages,
        release_label=release_label,
        distribution=distribution,
        days_to_keep=days_to_keep,
        num_to_keep=num_to_keep,
        existing_packages=existing_packages,
        s3_refs=(),
    )

    if dry_run:
        if not existing_packages:
            print(
                f"No published packages were discovered for {release_label}/ubuntu. "
                "Check repo access and the release label."
            )
        elif num_to_keep is None and days_to_keep is None:
            print("No deletion policy provided; pass --num-to-keep and/or --days-to-keep to preview removals.")
        print_publish_plan(plan)
        return plan

    if plan.packages_to_delete:
        deb_s3_delete_packages(plan.packages_to_delete, 'private', common_args, effective_key_homedir, dry_run)

    if cleanup_stale_s3:
        print("cleanup-stale-s3 is ignored in deb-s3 mode")

    return plan

def main():
    parser = argparse.ArgumentParser(description=publish_packages.__doc__)
    parser.add_argument('packages', type=pathlib.Path, nargs='*', default=[])
    parser.add_argument('--release-label', type=str, required=True)
    parser.add_argument('--apt-repo', type=str, required=True)
    parser.add_argument('--distribution', type=str, required=True)
    parser.add_argument('--organization', type=str, default='locusrobotics')
    parser.add_argument('--cleanup-stale-s3', action='store_true',
                        help='Also delete S3 artifacts no longer tracked by aptly')
    parser.add_argument('--keys', type=pathlib.Path, nargs='+')
    parser.add_argument('--days-to-keep', type=int)
    parser.add_argument('--num-to-keep', type=int)
    parser.add_argument('--key-homedir', type=str, default="/home/tailor/.gnupg")
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    publish_packages(**vars(args))
    sys.exit(0)


if __name__ == '__main__':
    main()
