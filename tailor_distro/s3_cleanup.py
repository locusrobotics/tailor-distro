#!/usr/bin/python3
import argparse
import bisect
import sys

from datetime import datetime, timedelta
from typing import Iterable, Set, Optional

import boto3
import click

from . import (
    list_s3_directories,
    delete_s3_directory
)


VERSION_DATE_FORMAT = "%Y%m%d.%H%M%S"


def build_directories_deletion_list(directories: Iterable[str], num_to_keep: int = None, date_to_keep: datetime = None) -> Set[str]:
    """Return the directories to delete given retention rules."""
    sorted_directories = sorted(set(directories))
    delete_directories = set()

    if num_to_keep is not None:
        delete_directories.update(sorted_directories[:-num_to_keep])

    if date_to_keep is not None:
        date_string = date_to_keep.strftime(VERSION_DATE_FORMAT)
        oldest_to_keep = bisect.bisect_left(sorted_directories, date_string)
        delete_directories.update(sorted_directories[:oldest_to_keep])

    return delete_directories


def is_valid_directory(directory_name: str) -> bool:
    """Return true if an S3 directory matches the configured version timestamp format."""
    try:
        datetime.strptime(directory_name, VERSION_DATE_FORMAT)
        return True
    except ValueError:
        return False



def cleanup_change_logs(
    apt_repo: str,
    release_label: str,
    days_to_keep: int = None,
    num_to_keep: int = None,
    dry_run: bool = False,
) -> None:
    """Cleanup change logs under {release_label}/changes according to retention rules.
    :param release_label: Release label of apt repo to target.
    :param apt_repo: S3 bucket where to publish release label.
    :param days_to_keep: (Optional) Age in days at which old images should be cleaned up.
    :param num_to_keep: (Optional) Quantity of old images to keep.
    :param dry_run: If true, only print the images that would be deleted without actually deleting them.
    """
    s3_client=boto3.client("s3")
    s3_resource = boto3.resource("s3")

    changes_prefix = f"{release_label}/changes"
    changes_directories = list_s3_directories(s3_client, apt_repo, changes_prefix)

    valid_directories = set()
    for directory_name in changes_directories:
        if is_valid_directory(directory_name):
            valid_directories.add(directory_name)
        else:
            click.echo(f"Skipping invalid directory name: {changes_prefix}/{directory_name}/")

    if days_to_keep is not None:
        date_to_keep: Optional[datetime] = datetime.now() - timedelta(days=days_to_keep)
    else:
        date_to_keep = None

    versions_to_delete = build_directories_deletion_list(valid_directories, num_to_keep, date_to_keep)
    changes_directories_to_delete = {f"{changes_prefix}/{version}/" for version in versions_to_delete}

    if not dry_run:
        delete_s3_directory(s3_resource, changes_directories_to_delete, apt_repo)
    else:
        click.echo("[DRY RUN] Would delete change logs from repo:")
        for prefix in sorted(changes_directories_to_delete):
            click.echo(prefix)


def main():
    parser = argparse.ArgumentParser(description=cleanup_change_logs.__doc__)
    parser.add_argument("--release-label", type=str, required=True)
    parser.add_argument("--apt-repo", type=str, required=True)
    parser.add_argument("--days-to-keep", type=int)
    parser.add_argument("--num-to-keep", type=int)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    sys.exit(cleanup_change_logs(**vars(args)))

if __name__ == "__main__":
    main()
