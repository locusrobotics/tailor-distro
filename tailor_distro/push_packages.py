#!/usr/bin/python3
import argparse
import pathlib
import subprocess


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


def main():
    parser = argparse.ArgumentParser(description='Push a set of packages to s3.')
    parser.add_argument('packages', type=pathlib.Path, nargs='+')
    parser.add_argument('--release-track', type=str, required=True)
    parser.add_argument('--endpoint', type=str, required=True)
    args = parser.parse_args()

    # TODO(pbovbel) remove old builds
    # num_to_keep = 10
    # days_to_keep = 30

    repo_name = "locus-{}-main".format(args.release_track)

    new_repo = aptly_create_repo(repo_name)

    for package in args.packages:
        aptly_add_package(repo_name, package)

    aptly_publish_repo(repo_name, args.release_track, args.endpoint, new_repo)


if __name__ == '__main__':
    main()
