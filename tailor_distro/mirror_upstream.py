#!/usr/bin/python3
import argparse
import pathlib
import subprocess
import sys
import yaml

from typing import TextIO, Iterable, Set, Mapping, Any
from jinja2 import Environment, BaseLoader

from . import aptly_configure, run_command, gpg_import_keys, deb_s3_common_args, deb_s3_list_packages


def gpg_receive_keys(upstream_keys: Iterable[str], keyservers: Iterable[str]):
    """ Receive keys for upstream repositories from keyservers """
    for keyserver in keyservers:
        try:
            run_command([
                'gpg1', '--no-default-keyring', '--keyring', 'trustedkeys.gpg', '--keyserver', keyserver,
                '--recv-keys', *upstream_keys
            ])
            break
        except subprocess.CalledProcessError:
            pass
    else:
        raise RuntimeError(f"Unable to obtain keys {' '.join(upstream_keys)} from {' '.join(keyservers)}")


def create_mirror(mirror_configurations: Mapping[str, Any], architectures: Iterable[str]) -> Iterable[str]:
    mirrors = []
    for mirror, data in mirror_configurations.items():
        for upstream_distribution in data['distributions']:
            label = f'{mirror}-{upstream_distribution}'
            command = [
                'aptly', 'mirror', 'create', f"-architectures={','.join(architectures)}"
            ]
            try:
                filter_string = (' | '.join(data['filters']))
                command.extend([
                    f"-filter={filter_string}", '-filter-with-deps'
                ])
            except KeyError:
                pass

            command.extend([
                label, data['url'], upstream_distribution, *data['components']
            ])

            run_command(command)
            mirrors.append(label)

    return mirrors


def pull_mirror(mirrors: Iterable[str], version: str):
    snapshots = []
    for mirror in mirrors:
        label = f'mirror-{mirror}-{version}'
        run_command(['aptly', 'mirror', 'update', '-max-tries=5', mirror])
        run_command(['aptly', 'snapshot', 'create', label, 'from', 'mirror', mirror])
        snapshots.append(label)
    return snapshots


def publish_mirror(snapshots: Iterable[str], version: str, architectures: Iterable[str], distribution: str,
                   apt_repo: str, endpoint: str):
    master_label = f'mirror-{version}'
    run_command(['aptly', 'snapshot', 'merge', '-latest', master_label, *snapshots])

    run_command([
        'aptly', 'publish', 'snapshot',
        f"-architectures={','.join(architectures)}",
        f'-distribution={distribution}-mirror', f'-origin={apt_repo}',
        '-label=locus-tailor', '-force-overwrite', f'-component=main', master_label, endpoint
    ])


def mirror_upstream(upstream_template: TextIO, version: str, apt_repo: str, release_track: str, distribution: str,
                    keys: Iterable[pathlib.Path] = [], force_mirror: bool = False, publish: bool = False):
    """Create and publish an upstream mirror.
    :param upstream_template: Template containing upstream repository operation.
    :param version: Snapshot version tag.
    :param apt_repo: Repository where to publish packages
    :param release_track: Release track
    :param distribution: Distribution of interest.
    :param keys: (Optional) GPG keys to use while publishing.
    :param force_mirror: (Optional) Force mirror creation even if one already exists.
    :param publish: (Optional) Flag to enable publishing mirror to endpoint.
    """
    context = {
        'distribution': distribution
    }

    # Check if mirror already exists
    common_args = deb_s3_common_args(apt_repo, 'ubuntu', distribution + "-mirror", release_track)

    packages = deb_s3_list_packages(common_args)

    if packages and not force_mirror:
        print(f"Found mirror in {apt_repo}, skipping mirror creation.", file=sys.stderr)
        return

    # Configure aptly endpoint
    endpoint = aptly_configure(apt_repo, release_track)

    # Import publishing key
    gpg_import_keys(keys)

    # Load configuration from yaml
    upstream_yaml = Environment(loader=BaseLoader()).from_string(upstream_template.read()).render(**context)
    upstream = yaml.safe_load(upstream_yaml)
    print(upstream_yaml, file=sys.stderr)

    # Trust keys from upstream repositories
    upstream_keys: Set[str] = set()

    for _, data in upstream['mirrors'].items():
        try:
            upstream_keys.update(data['keys'])
        except KeyError:
            pass

    if upstream_keys:
        gpg_receive_keys(upstream_keys, upstream['keyservers'])

    # Create upstream mirrors
    mirrors = create_mirror(upstream['mirrors'], upstream['architectures'])

    # Update and snapshot mirrors
    snapshots = pull_mirror(mirrors, version)

    # Merge and publish mirror
    if publish:
        publish_mirror(snapshots, version, upstream['architectures'], distribution, apt_repo, endpoint)


def main():
    parser = argparse.ArgumentParser(description=mirror_upstream.__doc__)
    parser.add_argument('upstream_template', type=argparse.FileType('r'))
    parser.add_argument('--version', type=str, required=True)
    parser.add_argument('--apt-repo', type=str, required=True)
    parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--distribution', type=str, required=True)
    parser.add_argument('--keys', type=pathlib.Path, nargs='+')
    parser.add_argument('--force-mirror', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()

    sys.exit(mirror_upstream(**vars(args)))


if __name__ == '__main__':
    main()
