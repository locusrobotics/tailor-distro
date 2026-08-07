#!/usr/bin/python3
import argparse
import sys

from typing import Sequence

import boto3
import click


def cleanup_deleted_objects(
    apt_repo: str,
    release_label: str,
    distribution: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Remove all versions and delete markers for soft-deleted objects under
    {release_label}/ubuntu/pool/{distribution} in the apt_repo bucket.
    :param apt_repo: Target S3 bucket. Accepts a raw bucket name or an ``s3://<bucket>`` URL.
    :param release_label: Release label directory to scan for deleted objects.
    :param distribution: Ubuntu distribution subdirectory to scope the scan.
    :param dry_run: If true, only print what would be deleted without actually deleting anything.
    :param verbose: If true, print every key and version being deleted.
    """

    # Accept both a raw bucket name and an ``s3://<bucket>`` URL so this command can be
    # invoked consistently with others in this repo (e.g. publish_packages) that use s3:// URLs.
    apt_repo = apt_repo.removeprefix("s3://")

    s3_client = boto3.client("s3")
    prefix = f"{release_label}/ubuntu/pool/{distribution}/"
    paginator = s3_client.get_paginator("list_object_versions")

    # Pass 1: collect only the key names whose latest version is a delete marker,
    # using the IsLatest flag to avoid loading all versions into memory.
    deleted_keys = set()
    for page in paginator.paginate(Bucket=apt_repo, Prefix=prefix):
        for marker in page.get("DeleteMarkers", []):
            if marker["IsLatest"]:
                deleted_keys.add(marker["Key"])

    if not deleted_keys:
        click.echo(f"No deleted objects found under s3://{apt_repo}/{prefix}")
        return 0

    click.echo(f"Found {len(deleted_keys)} deleted object(s) to purge.")
    if verbose or dry_run:
        for key in sorted(deleted_keys):
            click.echo(f"  {key}")
    click.echo("")

    if dry_run:
        click.echo("[DRY RUN] No changes made. Re-run without --dry-run to apply.")
        return 0

    def delete_batch(objects: Sequence[dict[str, str]]) -> tuple[set[str], int, int]:
        """Delete S3 objects in batches of 1000.
        Returns (failed_keys, deleted_count, error_count).
        """
        failed_keys: set[str] = set()
        deleted_count = 0
        error_count = 0
        for i in range(0, len(objects), 1000):
            batch = objects[i : i + 1000]
            response = s3_client.delete_objects(
                Bucket=apt_repo,
                Delete={"Objects": batch, "Quiet": not verbose},
            )
            errors = response.get("Errors", [])
            # With Quiet=True, S3 only returns errors (not Deleted entries).
            # Successful deletions = batch size minus error count.
            deleted_count += len(batch) - len(errors)
            if verbose:
                for deleted in response.get("Deleted", []):
                    click.echo(f"  Deleted: {deleted['Key']} (VersionId={deleted.get('VersionId')})")
            for error in errors:
                click.echo(
                    f"  ERROR: {error['Key']} (VersionId={error.get('VersionId')}): "
                    f"{error['Code']} - {error['Message']}",
                    err=True,
                )
                failed_keys.add(error["Key"])
                error_count += 1
        return failed_keys, deleted_count, error_count

    # Pass 2: stream-flush versions incrementally to keep memory bounded.
    # Markers are handled in a separate pass 3 so they are never accumulated in memory.
    version_buffer: list[dict[str, str]] = []
    version_failed_keys: set[str] = set()
    total_deleted = 0
    total_errors = 0

    for page in paginator.paginate(Bucket=apt_repo, Prefix=prefix):
        for version in page.get("Versions", []):
            key = version["Key"]
            # Detect keys that have been restored since pass 1 and skip them.
            if version.get("IsLatest") and key in deleted_keys:
                click.echo(f"  Skipping restored object: {key}", err=True)
                deleted_keys.discard(key)
                continue
            if key in deleted_keys:
                version_buffer.append({"Key": key, "VersionId": version["VersionId"]})

        # Flush versions incrementally as batches of 1000 accumulate.
        while len(version_buffer) >= 1000:
            fk, dc, ec = delete_batch(version_buffer[:1000])
            version_failed_keys |= fk
            total_deleted += dc
            total_errors += ec
            del version_buffer[:1000]

    # Flush any remaining versions.
    if version_buffer:
        fk, dc, ec = delete_batch(version_buffer)
        version_failed_keys |= fk
        total_deleted += dc
        total_errors += ec

    click.echo(f"Versions: deleted {total_deleted}, errors {total_errors}.")

    # Pass 3: stream-delete markers for keys whose versions were all removed successfully.
    # Streaming here avoids accumulating all markers in memory (a key can have multiple
    # delete markers, so markers_to_delete could be very large for deep version histories).
    # A marker is skipped when any of its key's version deletions failed to prevent the
    # object from being resurrected (an old version becoming the new latest).
    marker_buffer: list[dict[str, str]] = []
    marker_failed_keys: set[str] = set()
    marker_deleted = 0
    marker_errors = 0
    skipped_markers = 0

    for page in paginator.paginate(Bucket=apt_repo, Prefix=prefix):
        for marker in page.get("DeleteMarkers", []):
            if marker["Key"] not in deleted_keys:
                continue
            if marker["Key"] in version_failed_keys:
                skipped_markers += 1
                continue
            marker_buffer.append({"Key": marker["Key"], "VersionId": marker["VersionId"]})

        while len(marker_buffer) >= 1000:
            fk, dc, ec = delete_batch(marker_buffer[:1000])
            marker_failed_keys |= fk
            marker_deleted += dc
            marker_errors += ec
            del marker_buffer[:1000]

    if marker_buffer:
        fk, dc, ec = delete_batch(marker_buffer)
        marker_failed_keys |= fk
        marker_deleted += dc
        marker_errors += ec

    if skipped_markers:
        click.echo(
            f"  Skipping {skipped_markers} delete marker(s) for keys with version deletion errors.",
            err=True,
        )
    click.echo(f"Markers: deleted {marker_deleted}, errors {marker_errors}.")

    if version_failed_keys or marker_failed_keys:
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description=cleanup_deleted_objects.__doc__)
    parser.add_argument("--release-label", type=str, required=True)
    parser.add_argument(
        "--apt-repo",
        type=str,
        required=True,
        help="Target S3 bucket. Accepts a raw bucket name or an s3://<bucket> URL.",
    )
    parser.add_argument("--distribution", type=str, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    sys.exit(cleanup_deleted_objects(**vars(args)))

if __name__ == "__main__":
    main()
