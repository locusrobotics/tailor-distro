#!/usr/bin/python3
import argparse
import pathlib
import subprocess


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('packages', type=pathlib.Path, nargs='+', required=True)
    parser.add_argument('--release-track', type=str, required=True)
    # parser.add_argument('--release', action='store_true')
    args = parser.parse_args()

    num_to_keep = 10
    days_to_keep = 30

    repo_name = "locus-{}-main".format(args.release_track)

    try:
        subprocess.run(['aptly', 'create', 'repo', repo_name], check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if 'local repo with name {} already exists'.format(repo_name) not in e.output:
            raise

    for package in args.packages:
        # package_name = package.name
        subprocess.run(['aptly', 'repo', 'add', repo_name, package], check=True)

    subprocess.run(['aptly', 'pubish', 'repo', repo_name, package], check=True)


if __name__ == '__main__':
    main()
