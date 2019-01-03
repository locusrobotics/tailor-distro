#!/usr/bin/python3
import argparse
import pathlib
import subprocess
import sys
import yaml

from typing import TextIO, Iterable, Set
from jinja2 import Environment, BaseLoader

from . import aptly_configure, run_command, gpg_import_keys


# TODO(pbovbel) implement skipping mirror creation with force_mirror
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

    upstream_yaml = Environment(loader=BaseLoader()).from_string(upstream_template.read()).render(**context)
    upstream = yaml.safe_load(upstream_yaml)
    print(upstream_yaml, file=sys.stderr)
    snapshots = []
    mirrors = []
    architectures = ','.join(upstream['architectures'])

    # Configure aptly endpoint
    aptly_endpoint = aptly_configure(apt_repo, release_track)

    # Import publishing key
    gpg_import_keys(keys)

    # Trust keys from upstream repositories
    upstream_keys: Set[str] = set()

    for mirror, data in upstream['mirrors'].items():
        try:
            upstream_keys.update(data['keys'])
        except KeyError:
            pass

    if upstream_keys:
        for keyserver in upstream['keyservers']:
            try:
                run_command([
                    'gpg1', '--no-default-keyring', '--keyring', 'trustedkeys.gpg', '--keyserver', keyserver,
                    '--recv-keys', *upstream_keys
                ])
                break
            except subprocess.CalledProcessError:
                pass
        else:
            raise RuntimeError(f"Unable to obtain keys {' '.join(data['keys'])} for {mirror}")

    # Create upstream mirrors
    for mirror, data in upstream['mirrors'].items():
        for upstream_distribution in data['distributions']:
            label = f'{mirror}-{upstream_distribution}'
            command = [
                'aptly', 'mirror', 'create', f'-architectures={architectures}'
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

    # Update and snapshot mirrors
    for mirror in mirrors:
        label = f'mirror-{mirror}-{version}'
        run_command(['aptly', 'mirror', 'update', '-max-tries=5', mirror])
        run_command(['aptly', 'snapshot', 'create', label, 'from', 'mirror', mirror])
        snapshots.append(label)

    # Merge and publish mirror
    master_label = f'mirror-{version}'
    run_command(['aptly', 'snapshot', 'merge', '-latest', master_label, *snapshots])
    if publish:
        run_command([
            'aptly', 'publish', 'snapshot', f'-architectures={architectures}', f'-distribution={distribution}-mirror',
            '-label=upstream', '-force-overwrite', f'-component=main', master_label, aptly_endpoint
        ])


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
