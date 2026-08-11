__version__ = '0.0.0'

import argparse
import click
import gzip
import json
import lzma
import os
import pathlib
import re
import subprocess
import sys
try:
    import yaml
except ModuleNotFoundError:
    pass

from collections import namedtuple
from typing import Iterable, List, Optional


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


PackageEntry = namedtuple("PackageEntry", "name version arch")
S3PackageRef = namedtuple("S3PackageRef", "name version arch s3_key s3_version_id")

DEB_FILENAME_PATTERNS = [
    re.compile(r'^(?P<name>.+)_(?P<version>.+)_(?P<arch>[^_]+)_(?P<distribution>[^_]+)\.deb$'),
    re.compile(r'^(?P<name>.+)_(?P<version>.+)_(?P<arch>[^_]+)\.deb$'),
]

APTLY_BIN = "aptly"


def aptly_repo_name(release_label: str, distribution: str) -> str:
    """Generate a consistent aptly local repo name."""
    return f"{release_label}-{distribution}"


def aptly_ensure_repo(repo_name: str, distribution: str) -> None:
    """Create an aptly local repo if it doesn't already exist."""
    result = subprocess.run(
        [APTLY_BIN, 'repo', 'show', repo_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        run_command([
            APTLY_BIN, 'repo', 'create',
            f'-distribution={distribution}',
            '-component=main',
            repo_name,
        ])


def aptly_repo_exists(repo_name: str) -> bool:
    """Return whether an aptly local repo already exists."""
    result = subprocess.run(
        [APTLY_BIN, 'repo', 'show', repo_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return result.returncode == 0


def aptly_add_packages(repo_name: str, packages: Iterable[pathlib.Path]) -> None:
    """Add .deb packages to an aptly local repo."""
    pkg_list = list(packages)
    if not pkg_list:
        return
    run_command([APTLY_BIN, 'repo', 'add', repo_name, *map(str, pkg_list)])


def aptly_list_packages(repo_name: str) -> List[PackageEntry]:
    """List all packages in an aptly local repo."""
    result = subprocess.run(
        [APTLY_BIN, 'repo', 'search', repo_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    entries = []
    for line in result.stdout.decode().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # aptly package refs are in name_version_arch format
        parts = line.rsplit('_', 2)
        if len(parts) == 3:
            entries.append(PackageEntry(name=parts[0], version=parts[1], arch=parts[2]))
    return entries


def aptly_remove_packages(repo_name: str, packages: Iterable[PackageEntry],
                          dry_run: bool = False,
                          max_command_chars: int = 1000000) -> None:
    """Remove specific package versions from an aptly local repo."""
    pkg_list = list(packages)
    if not pkg_list:
        return

    base_command = [APTLY_BIN, 'repo', 'remove', repo_name]
    current_queries: List[str] = []
    current_length = sum(len(part) for part in base_command) + len(base_command) - 1

    for pkg in pkg_list:
        query = f'Name (= {pkg.name}), $Version (= {pkg.version}), $Architecture (= {pkg.arch})'
        query_length = len(query) + 1

        if current_queries and current_length + query_length > max_command_chars:
            command = [*base_command, *current_queries]
            if dry_run:
                print(' '.join(command))
            else:
                run_command(command)
            current_queries = []
            current_length = sum(len(part) for part in base_command) + len(base_command) - 1

        current_queries.append(query)
        current_length += query_length

    if current_queries:
        command = [*base_command, *current_queries]
        if dry_run:
            print(' '.join(command))
        else:
            run_command(command)


def aptly_publish(aptly_endpoint: str, distribution: str, gpg_key: Optional[str],
                  repo_name: str, dry_run: bool = False) -> None:
    """Publish or update an aptly repo to an S3 endpoint."""
    sign_args = ['-skip-signing'] if (dry_run or gpg_key is None) else [f'-gpg-key={gpg_key}', '-batch']

    # Try updating an existing publication; fall back to initial publish
    update_result = subprocess.run(
        [APTLY_BIN, 'publish', 'update', '-force-overwrite', *sign_args, distribution, aptly_endpoint],
        stderr=subprocess.PIPE
    )
    if update_result.returncode != 0:
        run_command([
            APTLY_BIN, 'publish', 'repo',
            f'-distribution={distribution}',
            '-force-overwrite',
            *sign_args,
            repo_name,
            aptly_endpoint,
        ])


def _read_apt_packages_index(index_path: pathlib.Path) -> str:
    if index_path.suffix == '.gz':
        with gzip.open(index_path, 'rt', encoding='utf-8') as package_file:
            return package_file.read()

    if index_path.suffix == '.xz':
        with lzma.open(index_path, 'rt', encoding='utf-8') as package_file:
            return package_file.read()

    if index_path.suffix == '.lz4':
        output = run_command(['lz4', '-d', '-c', str(index_path)], stdout=subprocess.PIPE)
        return output.stdout.decode('utf-8')

    return index_path.read_text(encoding='utf-8')


def apt_list_published_packages(release_label: str, distribution: str,
                                component: str = 'main',
                                apt_lists_dir: pathlib.Path = pathlib.Path('/var/lib/apt/lists')) -> List[PackageEntry]:
    """List packages for a published repo using the local APT cache.

    This reads the local APT list metadata for entries that match the standard
    published repo layout: <host>/<release_label>/ubuntu dists/<distribution>/<component>.
    """
    pattern = f'*_{release_label}_ubuntu_dists_{distribution}_{component}_binary-*Packages*'
    package_indexes = sorted(path for path in apt_lists_dir.glob(pattern) if path.is_file())

    entries: List[PackageEntry] = []
    for index_path in package_indexes:
        package_name = None
        package_version = None
        package_arch = None

        for line in _read_apt_packages_index(index_path).splitlines():
            if not line:
                if package_name and package_version and package_arch:
                    entries.append(PackageEntry(package_name, package_version, package_arch))
                package_name = None
                package_version = None
                package_arch = None
                continue

            if line.startswith('Package: '):
                package_name = line[len('Package: '):]
            elif line.startswith('Version: '):
                package_version = line[len('Version: '):]
            elif line.startswith('Architecture: '):
                package_arch = line[len('Architecture: '):]

        if package_name and package_version and package_arch:
            entries.append(PackageEntry(package_name, package_version, package_arch))

    return entries


def parse_deb_package_entry(filename: str, distribution: Optional[str] = None,
                            package_prefix: Optional[str] = None) -> Optional[PackageEntry]:
    for pattern in DEB_FILENAME_PATTERNS:
        match = pattern.match(filename)
        if match:
            if distribution is not None and match.groupdict().get('distribution') not in (None, distribution):
                continue

            package_name = match.group('name')
            if package_prefix is not None and not package_name.startswith(package_prefix):
                continue

            return PackageEntry(
                package_name,
                match.group('version'),
                match.group('arch'),
            )

    return None


def s3_list_package_refs(apt_repo: str, release_label: str,
                         distribution: str,
                         package_prefix: str = 'locusrobotics-') -> List[S3PackageRef]:
    """List all S3 object versions as S3PackageRef entries for the given release label pool."""
    import boto3  # type: ignore[import-not-found]

    bucket_name = get_bucket_name(apt_repo)
    prefix = f"{release_label}/ubuntu/pool/"
    s3_client = boto3.client("s3")
    paginator = s3_client.get_paginator("list_object_versions")

    refs: List[S3PackageRef] = []
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for entry in page.get("Versions", []):
            key = entry["Key"]
            if not key.endswith(".deb"):
                continue

            filename = pathlib.Path(key).name
            package_entry = parse_deb_package_entry(
                filename,
                distribution=distribution,
                package_prefix=package_prefix,
            )
            if package_entry is None:
                continue

            refs.append(S3PackageRef(
                package_entry.name,
                package_entry.version,
                package_entry.arch,
                key,
                entry["VersionId"],
            ))

    return refs


def s3_list_published_packages(apt_repo: str, release_label: str,
                               distribution: str,
                               package_prefix: str = 'locusrobotics-') -> List[PackageEntry]:
    """List published packages by scanning remote S3 object history under the repo pool."""
    refs = s3_list_package_refs(apt_repo, release_label, distribution, package_prefix)
    seen_entries: set = set()
    entries: List[PackageEntry] = []
    for ref in refs:
        entry = PackageEntry(ref.name, ref.version, ref.arch)
        if entry not in seen_entries:
            seen_entries.add(entry)
            entries.append(entry)
    return entries


def s3_delete_package_refs(apt_repo: str, refs: Iterable, dry_run: bool = False) -> None:
    """Delete S3 object versions for the given S3PackageRef entries in batches."""
    import boto3  # type: ignore[import-not-found]

    ref_list = list(refs)
    if not ref_list:
        return

    bucket_name = get_bucket_name(apt_repo)
    s3_client = boto3.client("s3")
    _BATCH = 1000
    for i in range(0, len(ref_list), _BATCH):
        batch = ref_list[i:i + _BATCH]
        if dry_run:
            for ref in batch:
                print(f"  DELETE S3 {ref.s3_key}")
        else:
            s3_client.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": [{"Key": r.s3_key, "VersionId": r.s3_version_id} for r in batch]},
            )


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
    upload_threads = int(os.environ.get('TAILOR_DEB_S3_UPLOAD_THREADS', '8'))
    skip_existing_check = os.environ.get('TAILOR_DEB_S3_SKIP_EXISTING_CHECK', '1') != '0'

    if dry_run:
        gpg_key = None
    else:
        gpg_key = get_gpg_key_id(key_homedir)
    command = [
        DEB_S3_BIN, 'upload',
        *map(str, package_files),
        f'--visibility={visibility}', f'--sign={gpg_key}', '--gpg-provider=gpg', '--preserve-versions',
        f'--upload-threads={max(upload_threads, 1)}',
    ]
    if skip_existing_check:
        command.append('--skip-existing-check')
    command.extend(common_args)

    if dry_run:
        print(' '.join(command))
    else:
        run_command(command)


def list_s3_directories(s3_client, bucket, prefix) -> List[str]:
    """List direct child directories under an S3 prefix."""
    directories = []
    normalized_prefix = prefix.rstrip("/") + "/"
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=normalized_prefix, Delimiter="/"):
        for entry in page.get("CommonPrefixes", []):
            full_prefix = entry["Prefix"]
            name = full_prefix[len(normalized_prefix):].strip("/")
            directories.append(name)

    return directories


def delete_s3_directory(s3_resource, directory: Iterable[str], bucket: str):
    """
    Delete S3 directory, including all versions if versioning is enabled.
    """
    bucket_obj = s3_resource.Bucket(bucket)

    for prefix in sorted(set(directory)):
        click.echo(f"Deleting change logs under {prefix}")

        # Delete all versions if versioning is enabled
        object_versions = bucket_obj.object_versions.filter(Prefix=prefix)
        for version in object_versions:
            version.delete()

        # Also delete current objects (in case versioning is not enabled)
        for obj in bucket_obj.objects.filter(Prefix=prefix):
            obj.delete()

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
