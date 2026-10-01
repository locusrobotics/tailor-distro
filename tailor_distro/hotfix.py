import argparse
import re
from pathlib import Path, PurePosixPath

import yaml


def load_definition(path: Path) -> dict:
    definition = yaml.safe_load(path.read_text())
    if not isinstance(definition, dict):
        raise ValueError("Hotfix definition must be a mapping")
    name = definition.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Hotfix name must be lowercase and hyphen-separated")
    if not isinstance(definition.get("base_release"), str) or not definition["base_release"]:
        raise ValueError("Hotfix definition requires base_release")
    packages = definition.get("packages")
    if not isinstance(packages, dict) or not packages or not set(packages) <= {"ros1", "ros2"}:
        raise ValueError("Hotfix definition requires ros1 or ros2 repositories")
    for distro, repos in packages.items():
        if not isinstance(repos, dict) or not repos:
            raise ValueError(f"Hotfix {distro} must contain repositories")
        for repo_name, repo in repos.items():
            if not isinstance(repo_name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", repo_name):
                raise ValueError("Invalid hotfix repository name")
            if not isinstance(repo, dict) or any(
                not isinstance(repo.get(key), str) or not repo[key] for key in ("url", "version")
            ):
                raise ValueError(f"Hotfix {distro}/{repo_name} requires url and version")
            whitelist = repo.get("whitelist")
            if whitelist is not None and (not isinstance(whitelist, list) or not whitelist or
                                          any(not isinstance(pkg, str) or not pkg for pkg in whitelist)):
                raise ValueError(f"Invalid whitelist for {distro}/{repo_name}")
    return definition


def selected_packages(definition: dict, graph, distro: str) -> list[str]:
    selected = set()
    for repo_name, repo in definition["packages"].get(distro, {}).items():
        available = {
            name for name, pkg in graph.packages[distro].items()
            if PurePosixPath(pkg.path).parts[0] == repo_name
        }
        if not available:
            raise ValueError(f"No packages found for hotfix repository {distro}/{repo_name}")
        names = set(repo.get("whitelist", available))
        if not names <= available:
            raise ValueError(f"Unknown packages in {distro}/{repo_name}: {sorted(names - available)}")
        selected.update(names)
    return sorted(selected)


def base_dependency_names(graph, distro: str, selected: list[str], base_release: str) -> list[str]:
    names = set()
    for package_name in selected:
        for dependency in graph.all_source_depends(package_name, distro):
            if dependency not in selected:
                names.add(graph.packages[distro][dependency].debian_name(graph.organization, base_release))
        if distro == "ros2":
            for dependency in graph.packages["ros2"][package_name].ros1_depends:
                if dependency in graph.packages.get("ros1", {}):
                    names.add(graph.packages["ros1"][dependency].debian_name(graph.organization, base_release))
    return sorted(names)


def prepare_hotfix(definition_path: Path, rosdistro_dir: Path, release_label: str) -> None:
    definition = load_definition(definition_path)
    if release_label != f"hotfix-{definition['name']}":
        raise ValueError("Hotfix release_label must be hotfix-<name>")
    for distro, repos in definition["packages"].items():
        distro_path = rosdistro_dir / f"{distro}.yaml"
        distro_data = yaml.safe_load(distro_path.read_text())
        for repo_name, overlay in repos.items():
            if repo_name not in distro_data["repositories"]:
                raise ValueError(f"Unknown base repository {distro}/{repo_name}")
            repo = distro_data["repositories"][repo_name]
            source = repo.setdefault("source", {"type": "git"})
            source.update(url=overlay["url"], version=overlay["version"])
            if "release" in repo or "whitelist" in overlay:
                release = repo.setdefault("release", {})
                release.update(url=overlay["url"], version=overlay["version"])
                release["tags"] = {"release": "{{ version }}"}
                if "whitelist" in overlay:
                    release["packages"] = overlay["whitelist"]
        distro_path.write_text(yaml.safe_dump(distro_data, sort_keys=False))


def main():
    parser = argparse.ArgumentParser(description="Apply hotfix refs to a copied rosdistro")
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--rosdistro-dir", type=Path, required=True)
    parser.add_argument("--release-label", required=True)
    args = parser.parse_args()
    prepare_hotfix(args.definition, args.rosdistro_dir, args.release_label)


if __name__ == "__main__":
    main()
