#!/usr/bin/python3
import argparse
import pathlib
import subprocess


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('packages', type=pathlib.Path, nargs='+')
    parser.add_argument('--release-track', type=str, required=True)
    args = parser.parse_args()

    # TODO(pbovbel) remove old builds
    # num_to_keep = 10
    # days_to_keep = 30

    repo_name = "locus-{}-main".format(args.release_track)

    try:
        cmd_create = ['aptly', 'repo', 'create', repo_name]
        print(' '.join(cmd_create))
        subprocess.run(cmd_create, check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        test_string = 'local repo with name {} already exists'.format(repo_name)
        if test_string not in e.stderr.decode():
            raise
        print(test_string)

    for package in args.packages:
        cmd_add = ['aptly', 'repo', 'add', repo_name, str(package)]
        print(' '.join(cmd_add))
        subprocess.run(cmd_add, check=True)

    cmd_publish = [
        'aptly', 'publish', 'repo', '-distribution={}'.format(args.release_track), repo_name, 's3:tailor-packages:'
    ]
    print(' '.join(cmd_publish))
    subprocess.run(cmd_publish, check=True)


if __name__ == '__main__':
    main()
