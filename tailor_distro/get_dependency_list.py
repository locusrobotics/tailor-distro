import argparse
import pathlib
import yaml

from .blossom import Graph


def main():
    parser = argparse.ArgumentParser(description="Get list of dependencies for all recipes")
    parser.add_argument("--graph", type=pathlib.Path, required=True)
    parser.add_argument("--recipe", type=pathlib.Path, required=True)
    parser.add_argument("--workspace", type=pathlib.Path, default=pathlib.Path("workspace"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    graph = Graph.from_yaml(args.graph)
    recipe = yaml.safe_load(args.recipe.read_text())

    deps_path = pathlib.Path(f"{args.workspace}/dependencies")
    deps_path.mkdir(parents=True, exist_ok=True)

    for flavour, flavour_data in recipe["flavours"].items():
        apt_deps = set()
        for ros_dist, dist_data in flavour_data["distributions"].items():
            root_packages = dist_data["root_packages"] or graph.packages[ros_dist].keys()

            for pkg_name in root_packages:
                deps = set(graph.all_apt_depends(pkg_name, ros_dist))
                apt_deps.update(deps)

        deps_file = deps_path / f"{flavour}-{graph.os_version}-{graph.release_label}-dependencies.txt"

        print(f"Writing {deps_file}...")
        deps_file.write_text("\n".join(sorted(apt_deps)))


if __name__ == '__main__':
    main()
