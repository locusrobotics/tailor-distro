import argparse
import shutil
from pathlib import Path

from debian_packager import environment_package_name, environment_package_version, package_debian
from debian_packager.debian_packager import installed_version

from .blossom import Graph
from .build_bundles import create_environment_packages
from .hotfix import load_definition, selected_packages


def create_hotfix_bundle(graph: Graph, definition: dict) -> None:
    if graph.release_label != f"hotfix-{definition['name']}":
        raise ValueError("Graph release label does not match the hotfix definition")

    dependencies = []
    selected_distros = []
    for distro in ("ros1", "ros2"):
        packages = selected_packages(definition, graph, distro)
        if not packages:
            continue
        selected_distros.append(distro)
        for package_name in packages:
            package = graph.packages[distro][package_name]
            debian_name = package.debian_name(*graph.debian_info)
            version = package.debian_version(graph.build_date)
            artifact = Path(f"{debian_name}_{version}_amd64_{graph.os_version}.deb")
            if not artifact.is_file():
                raise FileNotFoundError(f"Missing hotfix package: {artifact}")
            dependencies.append(f"{debian_name} (= {version})")

    create_environment_packages(
        graph.organization, graph.release_label, graph.package_name_release_label,
        graph.os_version, graph.build_date, definition["base_release"],
    )

    environment_distros = ["ros1", "ros2"] if "ros2" in selected_distros else selected_distros
    for distro in environment_distros:
        environment = environment_package_name(graph.organization, graph.package_name_release_label, distro)
        dependencies.append(f"{environment} (= {environment_package_version(graph.build_date, graph.os_version)})")
        base_environment = environment_package_name(graph.organization, definition["base_release"], distro)
        dependencies.append(f"{base_environment} (= {installed_version(base_environment)})")

    staging = Path("staging") / "hotfix_metapackage"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    package_debian(
        graph.release_label,
        environment_package_version(graph.build_date, graph.os_version),
        f"Hotfix {definition['name']}",
        "James Prestwood <jprestwood@locusrobotics.com>",
        graph.os_version,
        staging,
        run_depends=sorted(dependencies),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a limited hotfix and its environment")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--definition", type=Path, required=True)
    args = parser.parse_args()
    create_hotfix_bundle(Graph.from_yaml(args.graph), load_definition(args.definition))


if __name__ == "__main__":
    main()
