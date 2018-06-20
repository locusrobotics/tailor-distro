#!/usr/bin/python3
import argparse
import pathlib
import rosdistro
import subprocess
import yaml

from shutil import rmtree


def main():
    parser = argparse.ArgumentParser(description='Pull the contents of a ROS distribution to disk.')
    parser.add_argument('--src-dir', type=pathlib.Path, required=True)
    parser.add_argument('--github-key', type=str)
    parser.add_argument('--repositories-file', type=pathlib.Path, default='catkin.repos')
    parser.add_argument('--recipes', type=pathlib.Path, required=True)
    args = parser.parse_args()

    recipes = yaml.load(args.recipes.open())

    index = rosdistro.get_index(rosdistro.get_index_url())

    for distro_name in recipes['common']['rosdistros']:

        distro = rosdistro.get_distribution(index, distro_name)
        target_dir = args.src_dir / distro_name

        repositories = {}
        for repo in distro.repositories.items():
            repositories[repo[0]] = {
                'type': repo[1].source_repository.type,
                'url': repo[1].source_repository.url,  # TODO(pbovbel) insert github key into URL
                'version': repo[1].source_repository.version
            }

        if target_dir.exists():
            rmtree(str(target_dir))

        target_dir.mkdir(parents=True, exist_ok=True)

        repositories_file = args.src_dir / (distro_name + '.repos')
        repositories_file.write_text(yaml.dump({'repositories': repositories}))

        subprocess.run([
            "vcs", "import", str(target_dir),
            "--input", str(repositories_file),
            "--retry", str(3),
            "--recursive",
            "--shallow",
        ], check=True)


if __name__ == '__main__':
    main()
