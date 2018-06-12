#!/usr/bin/python3
import pathlib
import rosdistro
import subprocess
import yaml


def main():
    # TODO(pbovbel) make args
    # Args
    workspace_dir = pathlib.Path("workspace/src")
    repositories_file = pathlib.Path('catkin.repos')

    # Flavour
    ros_distro = "locus"
    # TODO(end)

    index = rosdistro.get_index(rosdistro.get_index_url())
    distro = rosdistro.get_distribution(index, ros_distro)

    repositories = {}
    for repo in distro.repositories.items():
        repositories[repo[0]] = {
            'type': repo[1].source_repository.type,
            'url': repo[1].source_repository.url,
            'version': repo[1].source_repository.version
        }

    try:
        workspace_dir.mkdir(parents=True)
    except FileExistsError:
        pass

    repositories_file.write_text(yaml.dump({'repositories': repositories}))

    subprocess.check_call(["vcs", "import", str(workspace_dir), "--input", str(repositories_file)])
    subprocess.check_call(["vcs", "pull", str(workspace_dir)])


if __name__ == '__main__':
    main()
